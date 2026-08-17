def quality_score(health, success, latency_ms, freshness_hours=0):
    health=max(0,min(100,float(health or 0)))
    success=max(0,min(100,float(success or 0)))
    latency=100 if not latency_ms else max(0,min(100,100-float(latency_ms)/20))
    freshness=max(0,min(100,100-float(freshness_hours)/24*20))
    return round(health*.55+success*.25+latency*.15+freshness*.05,2)

def source_state(health_rate, success_rate, previous_health=None):
    drop=(previous_health-health_rate) if previous_health is not None else 0
    if (drop>=50 and success_rate<40) or health_rate<15: return "quarantined"
    if drop>=30 or success_rate<55: return "degraded"
    return "active"

def lifecycle(health_rate, consecutive_failures, age_hours):
    if consecutive_failures>=5 or health_rate<15:return "dead"
    if consecutive_failures>=3 or health_rate<35:return "degraded"
    if age_hours>168 and health_rate<60:return "stale"
    return "active" if health_rate>=70 else "checking"
