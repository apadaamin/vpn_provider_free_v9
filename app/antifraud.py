import time
def risk_score(events, qualified):
    now=time.time()
    recent=[e for e in events if now-float(e.get("created",0))<=86400]
    velocity=len(recent)/24
    score=0
    if velocity>30: score+=35
    elif velocity>15: score+=20
    elif velocity>8: score+=10
    if qualified>20 and len(recent)>qualified*2: score+=20
    if any(e.get("type")=="repeated_pattern" for e in recent): score+=25
    return min(100,score)
def label(score): return "high" if score>=70 else ("medium" if score>=40 else "low")
