def test_smoke_imports():
    from wealthtax_agent import build_return
    from wealthtax_agent import explain_return
    from wealthtax_agent import graph
    from wealthtax_agent import llm
    from wealthtax_agent import main
    from wealthtax_agent import parse_docs
    from wealthtax_agent import reason_tax
    from wealthtax_agent import state

    assert main is not None
    assert graph is not None
    assert parse_docs is not None
    assert reason_tax is not None
    assert build_return is not None
    assert explain_return is not None
    assert state is not None
    assert llm is not None
