"""Explicit single-stock FinRL intent mapping, checked against upstream 7e98df4.

The policy vector is a proposal. Native cash/share limits determine the actual
intent. This helper submits no order and imports NumPy only when called.
"""
from copy import deepcopy
import math

from tradeoff.feedback.contracts import FeedbackError


def build_finrl_intent(env, policy_action, metadata):
    """Map an unmodified StockTradingEnv's supported ordinary execution policy.

    Call before env.step(), record the returned intent, then inspect the native
    transition afterward. Membership/turbulence liquidations and multi-asset
    ordering need a different adapter; silently guessing those is unsafe.
    """
    import numpy as np
    if env.stock_dim != 1 or env.member_col is not None or env.turbulence_threshold is not None:
        raise FeedbackError('UNSUPPORTED_FINRL_MODE', 'This example supports one stock without forced membership or turbulence execution')
    if env.day >= len(env.df.index.unique()) - 1:
        raise FeedbackError('FINRL_EPISODE_COMPLETE', 'The final FinRL day is terminal-only; do not record an executable intent for it')
    values = np.asarray(policy_action)
    cash, price, shares = (float(value) for value in env.state[:3])
    fee = float(env.buy_cost_pct[0])
    if (values.shape != (1,) or not np.isfinite(values).all() or np.any(np.abs(values)>1)
        or not all(math.isfinite(value) for value in (cash,price,shares,fee))
        or cash<0 or price<=0 or shares<0 or shares != int(shares) or not 0<=fee<1
        or isinstance(env.hmax,bool) or not isinstance(env.hmax,int) or env.hmax<=0):
        raise FeedbackError('INVALID_FINRL_STATE', 'Use a valid finite long-only state and bounded native policy action')
    # Keep NumPy's multiplication/truncation used by the upstream environment.
    proposal = int((values * env.hmax).astype(int)[0])
    quantity = min(proposal,int(cash // (price*(1+fee)))) if proposal>0 else -min(abs(proposal),int(shares))
    intent = deepcopy(metadata)
    intent.update(action='buy' if quantity>0 else 'sell' if quantity<0 else 'hold', quantity_delta=str(quantity),
                  reason=f'FinRL policy proposal {proposal}; executable intent {quantity}; native constraints applied')
    return intent
