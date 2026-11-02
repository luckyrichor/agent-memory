"""Pytest plugin for machines WITHOUT Docker.

Replaces Testcontainers' PostgresContainer with a throw-away local PostgreSQL cluster
(needs system postgresql-16 + postgresql-16-pgvector; set LOCALPG_BIN to override the bin dir).
Usage:  PYTHONPATH=scripts/dev .venv/bin/python -m pytest -p localpg
Never use this to claim a Docker-based gate passed; record that localpg was used."""
import os, shutil, socket, subprocess, tempfile
import testcontainers.community.postgres as tcp

PGBIN = os.environ.get("LOCALPG_BIN", "/usr/lib/postgresql/16/bin")

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def _run(cmd):
    return subprocess.run(["runuser", "-u", "claude", "--"] + cmd, check=True,
                          capture_output=True, text=True)

class LocalPostgres:
    def __init__(self, image=None, username="test", password="test", dbname="test", driver="psycopg", **kw):
        self.user, self.pw, self.db, self.driver = username, password, dbname, driver
        self.dir = tempfile.mkdtemp(prefix="pg-")
        os.chmod(self.dir, 0o777)
        self.port = _free_port()
    def __enter__(self):
        data = os.path.join(self.dir, "data")
        pwf = os.path.join(self.dir, "pw"); open(pwf, "w").write(self.pw); os.chmod(pwf, 0o644)
        _run([f"{PGBIN}/initdb", "-D", data, "-U", self.user, "--pwfile", pwf, "--auth=md5", "-E", "UTF8"])
        _run([f"{PGBIN}/pg_ctl", "-D", data, "-o", f"-p {self.port} -c listen_addresses=127.0.0.1 -c unix_socket_directories={self.dir} -c fsync=off -c max_connections=200",
              "-l", os.path.join(self.dir, "log"), "-w", "start"])
        env = dict(os.environ, PGPASSWORD=self.pw)
        subprocess.run([f"{PGBIN}/createdb", "-h", "127.0.0.1", "-p", str(self.port), "-U", self.user, self.db], check=True, env=env)
        return self
    def __exit__(self, *a):
        try: _run([f"{PGBIN}/pg_ctl", "-D", os.path.join(self.dir, "data"), "-m", "immediate", "stop"])
        finally: shutil.rmtree(self.dir, ignore_errors=True)
    def get_connection_url(self):
        return f"postgresql+{self.driver}://{self.user}:{self.pw}@127.0.0.1:{self.port}/{self.db}"

tcp.PostgresContainer = LocalPostgres
