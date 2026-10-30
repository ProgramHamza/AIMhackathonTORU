"""Pack consecutive sections while retaining original passage IDs and offsets."""
VERSION = 'section-batches-v1'


def section_batches(passages, limit=2400):
    if sum(len(p.text) for p in passages) <= limit:
        return [list(passages)] if passages else []
    sections, current = [], []
    for p in passages:
        if current and p.section != current[-1].section:
            sections.append(current)
            current = []
        current.append(p)
    if current:
        sections.append(current)
    batches, current = [], []
    for section in sections:
        if current and sum(len(p.text) for p in current + section) > limit:
            batches.append(current)
            current = []
        for p in section:
            if current and sum(len(q.text) for q in current) + len(p.text) > limit:
                batches.append(current)
                # Preserve the original section heading when breaking a large section.
                current = [section[0]] if section[0].kind == 'heading' and section[0].id != p.id else []
            current.append(p)
    if current:
        batches.append(current)
    return batches
