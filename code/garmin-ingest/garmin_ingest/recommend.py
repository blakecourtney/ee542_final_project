"""Conservative, explainable recommendations; not a medical or AI model."""
def recommend(metrics: dict, goal='endurance') -> list[str]:
    n = metrics['valid_sessions']
    if n == 0:
        return ['No valid activities yet. Sync workouts with distance and moving duration.']
    advice = [f'Analyzed {n} valid {metrics["activity_type"]} session(s), totaling {metrics["total_distance_km"]:.2f} km.']
    if n < 4:
        advice.append('Record at least four comparable workouts before evaluating pace trends.')
        advice.append('For now, focus on consistent training and logging how each session feels.')
        return advice
    change = metrics['recent_vs_previous_pace_change_pct']
    if change < -3:
        advice.append('Recent pace is faster than the preceding sessions. Check effort and recovery before increasing training difficulty.')
    elif change > 3:
        advice.append('Recent pace is slower. Consider differences in terrain, workout intent, fatigue, and recovery before adjusting your plan.')
    else:
        advice.append('Recent pace is broadly stable. Continue monitoring comparable workouts over time.')
    if goal == 'endurance':
        advice.append('For endurance, prioritize consistency and gradual changes rather than increasing intensity abruptly.')
    elif goal == 'pace':
        advice.append('For pace improvement, compare runs of similar distance, terrain, and effort.')
    return advice
