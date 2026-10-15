"""Replace this ordinary Python decision function with your own local policy.

It receives only closes visible through the current bar and the native position.
There is no LLM, network service, credential or separate execution simulator.
"""


def decide(history, position, *, lookback=3):
    """Buy a rise, close a fall, otherwise hold; never initiate a short."""
    if len(history) < lookback:
        return 'hold'
    if position == 0 and history[-1] > history[-lookback]:
        return 'buy'
    if position > 0 and history[-1] < history[-lookback]:
        return 'close'
    return 'hold'
