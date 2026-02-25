from wealthtax_agent.main import main


def test_streamlit_entrypoint_exposes_main_callable():
    assert callable(main)
