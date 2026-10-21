import pytest

from agent_memory.evals.model_policy import require_frozen_annotation_model


@pytest.mark.parametrize("model", ["glm-5.2", "minimax-m2.7", "deepseek-v4.1-flash"])
def test_frozen_annotation_roles_do_not_follow_judge_rotation(model):
    with pytest.raises(ValueError, match="owner confirmation"):
        require_frozen_annotation_model(model, ("deepseek-v4-pro", "mimo-v2.6-flash"))
