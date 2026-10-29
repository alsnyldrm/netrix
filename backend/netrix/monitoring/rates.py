def calculate_rate(previous, current, elapsed, speed=None):
    if not previous or elapsed <= 0 or elapsed > 3600:
        return None, None, "baseline" if not previous else "gap"
    if (
        current["uptime_ticks"] < previous["uptime_ticks"]
        or current["discontinuity_ticks"] != previous["discontinuity_ticks"]
    ):
        return None, None, "reset"
    delta_in = current["in_octets"] - previous["in_octets"]
    delta_out = current["out_octets"] - previous["out_octets"]
    if delta_in < 0 or delta_out < 0:
        return None, None, "reset"
    incoming, outgoing = delta_in * 8 / elapsed, delta_out * 8 / elapsed
    if speed and max(incoming, outgoing) > speed * 1.05:
        return None, None, "invalid"
    return incoming, outgoing, "valid"
