# coding: utf-8
"""Render dashboards in memory; private records never become report files."""
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo
from coach_courses import selected, task_states
from coach_metrics import events, metrics, DIMENSIONS


DASHBOARD_TIMEOUT_SECONDS = 45
REQUEST_TIMEOUT_SECONDS = 0.25


class _DeadlineReader:
    """A minimal HTTP-header reader that cannot outlive the dashboard deadline."""
    def __init__(self, connection, deadline):
        self._connection=connection
        self._deadline=deadline
        self.closed=False

    def _remaining(self):
        remaining=self._deadline-time.monotonic()
        if remaining<=0:
            raise socket.timeout('dashboard deadline expired')
        return remaining

    def readline(self, limit=-1):
        if limit==0:
            return b''
        line=bytearray()
        while limit<0 or len(line)<limit:
            self._connection.settimeout(min(REQUEST_TIMEOUT_SECONDS,self._remaining()))
            byte=self._connection.recv(1)
            if time.monotonic()>=self._deadline:
                raise socket.timeout('dashboard deadline expired')
            if not byte:
                return bytes(line)
            line.extend(byte)
            if byte==b'\n':
                return bytes(line)
        return bytes(line)

    def close(self):
        self.closed=True


def report_data(conn, catalog):
    from coach_state import resume
    enrollment=selected(conn)
    course=next((c for c in catalog['courses'] if enrollment and c['course_id']==enrollment['course_id']),None)
    row=conn.execute('SELECT body FROM plans ORDER BY seq DESC LIMIT 1').fetchone()
    current_plan=json.loads(row[0]) if row else None
    if current_plan and enrollment and (current_plan['course_id']!=enrollment['course_id'] or current_plan['week_id']!=enrollment['week_id']): current_plan=None
    if current_plan and enrollment:
        today=datetime.now(ZoneInfo(enrollment['timezone'])).date().isoformat()
        if current_plan['date']!=today or not course or current_plan['course_version']!=course['version']:
            current_plan=None
    state=resume(conn)
    return dict(generated_at=datetime.now(timezone.utc).isoformat(),enrollment=enrollment,course=course,
                task_states=task_states(conn,enrollment['course_id']) if enrollment else {},plan=current_plan,
                records=events(conn),repairs=state['pending_repairs'],dimensions=DIMENSIONS,
                study_sections=state['study_sections'],open_gaps=state['open_gaps'],
                debriefs=state['debriefs'],latest_debrief=state['latest_debrief'])


def render(data):
    data=dict(data)
    scopes={('', '')} | {(p['track'],'') for p in data['records']} | {(p['track'],p['competency']) for p in data['records']} | {('',p['competency']) for p in data['records']}
    now=datetime.fromisoformat(data['generated_at'].replace('Z','+00:00'))
    analytics=[]
    for track, competency in sorted(scopes):
        for period in ('all','30','7'):
            since=None if period=='all' else (now-timedelta(days=int(period))).isoformat()
            stats=metrics(data['records'],track or None,competency or None,since)
            stats.pop('evidence')
            analytics.append(dict(track=track,competency=competency,period=period,stats=stats))
    data['analytics']=analytics
    template=(Path(__file__).resolve().parents[1]/'assets/dashboard.html').read_text(encoding='utf-8')
    # JSON is a data island, never HTML; escape all HTML-significant characters.
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    return template.replace('__COACH_DATA__',payload)


def _known_legacy_dashboard(descriptor, size):
    """Recognize only pages produced by this exact private-report template."""
    try:
        template=(Path(__file__).resolve().parents[1]/'assets/dashboard.html').read_text(encoding='utf-8')
    except OSError:
        return False
    marker='__COACH_DATA__'
    if template.count(marker)!=1:
        return False
    prefix,suffix=template.split(marker)
    prefix=prefix.encode('utf-8');suffix=suffix.encode('utf-8')
    payload_start=b'{"generated_at":'
    if not suffix or size<len(prefix)+len(payload_start)+len(suffix)+1:
        return False
    try:
        os.lseek(descriptor,0,os.SEEK_SET)
        if os.read(descriptor,len(prefix))!=prefix or os.read(descriptor,len(payload_start))!=payload_start:
            return False
        os.lseek(descriptor,-len(suffix),os.SEEK_END)
        if os.read(descriptor,len(suffix))!=suffix:
            return False
        os.lseek(descriptor,-len(suffix)-1,os.SEEK_END)
        return os.read(descriptor,1)==b'}'
    except OSError:
        return False


def _safe_regular(stat_result):
    return (stat.S_ISREG(stat_result.st_mode) and stat_result.st_uid==os.getuid() and
            stat_result.st_nlink==1)


def _same_file(first, second):
    return (_safe_regular(second) and first.st_dev==second.st_dev and first.st_ino==second.st_ino and
            first.st_size==second.st_size)


def remove_legacy_dashboard(root):
    """Delete a prior generated private page, never a link or unrelated file."""
    path=Path(root)/'dashboard.html'
    try:
        initial=os.lstat(path)
    except OSError:
        return False
    if not _safe_regular(initial):
        return False
    nofollow=getattr(os,'O_NOFOLLOW',None)
    if nofollow is None:
        return False
    try:
        descriptor=os.open(path,os.O_RDONLY|nofollow)
    except OSError:
        return False
    try:
        opened=os.fstat(descriptor)
        if not _same_file(initial,opened):
            return False
        if not _known_legacy_dashboard(descriptor,opened.st_size):
            return False
        try:
            current=os.lstat(path)
        except OSError:
            return False
        if not _same_file(initial,current):
            return False
        try:
            os.unlink(path)
        except OSError:
            return False
        return True
    finally:
        os.close(descriptor)


def serve_dashboard(conn, catalog, on_ready, timeout=DASHBOARD_TIMEOUT_SECONDS):
    """Serve one token-protected in-memory report, then close the loopback socket."""
    timeout=max(0.0,min(float(timeout),DASHBOARD_TIMEOUT_SECONDS))
    deadline=time.monotonic()+timeout
    token_path='/dashboard/'+secrets.token_urlsafe(32)

    class LoopbackServer(HTTPServer):
        def get_request(self):
            request,address=super().get_request()
            request.settimeout(min(REQUEST_TIMEOUT_SECONDS,max(0.0,deadline-time.monotonic())))
            return request,address

        def handle_error(self, request, client_address):
            pass

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version='KnowLoop'
        sys_version=''

        def setup(self):
            super().setup()
            self.rfile.close()
            self.rfile=_DeadlineReader(self.connection,deadline)

        def _active(self):
            return time.monotonic()<deadline

        def log_message(self, format, *args):
            pass

        def log_request(self, code='-', size='-'):
            pass

        def _send(self, status, body=b'', content_type=None):
            if not self._active():
                self.close_connection=True
                return False
            self.send_response(status)
            self.send_header('Cache-Control','no-store, max-age=0, private')
            self.send_header('Pragma','no-cache')
            self.send_header('Expires','0')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Cross-Origin-Opener-Policy','same-origin')
            self.send_header('Cross-Origin-Resource-Policy','same-origin')
            self.send_header('Content-Security-Policy',"default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'")
            if content_type:
                self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Connection','close')
            self.end_headers()
            if body and getattr(self,'command',None)!='HEAD':
                self.wfile.write(body)
            return True

        def send_error(self, code, message=None, explain=None):
            self._send(code)

        def do_GET(self):
            if not self._active():
                self.close_connection=True
                return
            if self.path!=token_path:
                self._send(404)
                return
            try:
                body=render(report_data(conn,catalog)).encode('utf-8')
            except Exception:
                try:
                    self._send(500)
                except OSError:
                    pass
                return
            try:
                if not self._active():
                    self.close_connection=True
                    return
                if not self._send(200,body,'text/html; charset=utf-8'):
                    return
            except OSError:
                return
            self.server.page_served=True

        def do_HEAD(self):
            self._send(404)

        def do_POST(self):
            self._send(404)

    server=LoopbackServer(('127.0.0.1',0),DashboardHandler)
    server.page_served=False
    url=f'http://127.0.0.1:{server.server_port}{token_path}'
    try:
        on_ready(url)
        while not server.page_served:
            remaining=deadline-time.monotonic()
            if remaining<=0:
                break
            server.timeout=min(REQUEST_TIMEOUT_SECONDS,remaining)
            server.handle_request()
        return server.page_served
    finally:
        server.server_close()
