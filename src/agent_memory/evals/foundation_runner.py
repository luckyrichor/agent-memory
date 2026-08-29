from agent_memory.evals.schema import FoundationActual, FoundationCase, FoundationScore


def evaluate_foundation_case(
    case: FoundationCase,
    actual: FoundationActual,
) -> FoundationScore:
    if actual.tenant_id != case.tenant_id:
        raise ValueError("tenant mismatch")

    reasons: list[str] = []
    if actual.memory_type != case.expected_memory_type:
        reasons.append("memory_type_mismatch")
    if actual.scope_kind != case.expected_scope_kind:
        reasons.append("scope_kind_mismatch")
    if actual.content != case.expected_content:
        reasons.append("content_mismatch")
    if actual.status != "active":
        reasons.append("memory_not_active")

    return FoundationScore(passed=not reasons, reasons=tuple(reasons))
