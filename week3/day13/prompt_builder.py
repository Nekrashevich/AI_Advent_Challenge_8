WINDOW_N = 8


def _system(content):
    return {"role": "system", "content": content}


def build_messages(base_system, memory, profile, state, invariants, window_n=WINDOW_N):
    messages = [_system(base_system)]

    inv_block = invariants.as_prompt()
    if inv_block:
        messages.append(_system(inv_block))

    profile_block = profile.as_prompt()
    if profile_block:
        messages.append(_system(profile_block))

    state_block = state.as_prompt()
    if state_block:
        messages.append(_system(state_block))

    for block in memory.context_blocks():
        messages.append(_system(block))

    messages += memory.short_term[-window_n:]
    return messages
