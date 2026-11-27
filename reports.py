"""Publication jobs and service cohorts, scoped by workspace and WIB dates."""
import csv
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Response, abort, render_template, request


def register(app,connect):
    @app.get("/laporan")
    def combined_reports():
        today=datetime.now(ZoneInfo("Asia/Jakarta")).date()
        try:
            start=date.fromisoformat(request.args.get("start") or str(today-timedelta(days=29)))
            end=date.fromisoformat(request.args.get("end") or str(today))
            if start>end or end.year==9999: abort(400)
            lo=datetime.combine(start,datetime.min.time(),ZoneInfo("Asia/Jakarta"))
            hi=datetime.combine(end+timedelta(days=1),datetime.min.time(),ZoneInfo("Asia/Jakarta"))
        except ValueError: abort(400)
        with connect() as db:
            publication=db.execute("""SELECT coalesce(o.title,c.title,p.target_title,'Akun dilepas') AS akun,
                coalesce(o.platform,c.platform,'') AS platform,coalesce('oauth:'||p.oauth_id::text,p.channel::text) AS identitas,
                p.editorial_id AS materi, left(p.body,100) AS caption,p.state AS status,count(*) AS jumlah
                FROM posts p LEFT JOIN channels c ON c.id=p.channel LEFT JOIN oauth_accounts o ON o.id=p.oauth_id
                WHERE p.due >= %s AND p.due < %s GROUP BY 1,2,3,4,5,6 ORDER BY 1,4,6""",(lo,hi)).fetchall()
            stats=db.execute("""WITH conversations AS (
              SELECT t.id,t.resolved,t.owner_id,min(m.sent_at) FILTER(WHERE NOT m.outbound) AS arrived
              FROM desk_threads t JOIN desk_messages m ON m.thread=t.id GROUP BY t.id
            ), cohort AS (
              SELECT c.*, (SELECT min(m.sent_at) FROM desk_messages m WHERE m.thread=c.id AND m.outbound
              AND m.state IN ('Terkirim','Tersinkron','Otomatis') AND m.sent_at>=c.arrived) AS answered
              FROM conversations c WHERE c.arrived >= %s AND c.arrived < %s)
              SELECT coalesce(u.login,'Belum ditugaskan') AS petugas,count(*) AS percakapan,
              count(*) FILTER(WHERE c.resolved IS NULL) AS terbuka,count(c.resolved) AS selesai,
              count(answered) AS terjawab,round(avg(extract(epoch FROM answered-arrived))/60,1) AS respons_menit,
              round(avg(extract(epoch FROM resolved-arrived)) FILTER(WHERE resolved>=arrived)/60,1) AS resolusi_menit
              FROM cohort c LEFT JOIN public.studio_users u ON u.id=c.owner_id GROUP BY 1 ORDER BY 1""",(lo,hi)).fetchall()
            agents=db.execute("""SELECT coalesce(u.login,e.actor) AS petugas,
                count(*) FILTER(WHERE e.detail='Balasan terkirim') AS balasan,
                count(*) FILTER(WHERE e.detail='Selesai') AS penyelesaian,
                count(*) FILTER(WHERE e.detail='Petugas mengambil alih') AS pengambilalihan
                FROM desk_events e LEFT JOIN public.studio_users u ON e.actor='Pengguna '||u.id::text
                WHERE e.happened >= %s AND e.happened < %s AND e.detail IN ('Balasan terkirim','Selesai','Petugas mengambil alih')
                GROUP BY 1 ORDER BY 1""",(lo,hi)).fetchall()
            metrics=db.execute("""SELECT m.day AS tanggal,o.title AS akun,o.id AS akun_id,m.metric AS metrik,m.value AS nilai
                FROM metric_days m JOIN oauth_accounts o ON o.id=m.account WHERE day BETWEEN %s AND %s ORDER BY day DESC,o.id,metric""",(start,end)).fetchall()
        groups={"publikasi":publication,"layanan":stats,"metrik":metrics,"petugas":agents}
        export=request.args.get("csv")
        if export:
            if export not in groups: abort(400)
            out=io.StringIO()
            writer=csv.writer(out)
            rows=groups[export]
            headers={"publikasi":"akun platform identitas materi caption status jumlah","layanan":"petugas percakapan terbuka selesai terjawab respons_menit resolusi_menit","petugas":"petugas balasan penyelesaian pengambilalihan","metrik":"tanggal akun akun_id metrik nilai"}[export].split()
            writer.writerow(headers)
            for row in rows:
                values=[row[k] for k in headers]
                writer.writerow(["Belum tersedia" if v is None else "'"+v if isinstance(v,str) and v.lstrip().startswith(("=","+","-","@")) else v for v in values])
            return Response(out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":f"attachment; filename={export}-{start}-{end}.csv"})
        totals={s:sum(r["jumlah"] for r in publication if r["status"]==s) for s in ("Terbit","Gagal")}
        return render_template("studio.html",page="laporan",publication=publication,stats=stats,agents=agents,metrics=metrics,start=start,end=end,
            total=sum(r["jumlah"] for r in publication),totals=totals)
