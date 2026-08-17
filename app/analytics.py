import time
from .db import cx

def overview():
    with cx() as c:
        return {
          'dau': c.execute("SELECT COUNT(*) n FROM users WHERE last_seen>=?",(int(time.time())-86400,)).fetchone()['n'],
          'new_7d': c.execute("SELECT COUNT(*) n FROM users WHERE created>=?",(int(time.time())-7*86400,)).fetchone()['n'],
          'qualified_7d': c.execute("SELECT COUNT(*) n FROM referrals WHERE qualified=1 AND qualified_at>=?",(int(time.time())-7*86400,)).fetchone()['n'],
          'feedback_7d': c.execute("SELECT COUNT(*) n FROM configs WHERE created>=? AND (connected=1 OR reported_bad=1)",(int(time.time())-7*86400,)).fetchone()['n'],
        }

def retention():
    with cx() as c:
        return [dict(x) for x in c.execute("""SELECT date(created,'unixepoch') day,COUNT(*) new_users FROM users GROUP BY day ORDER BY day DESC LIMIT 14""")]
