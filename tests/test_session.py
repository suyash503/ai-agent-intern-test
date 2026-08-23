from src.agent.session import Session, SessionStore


def test_short_followup_is_expanded_with_the_previous_topic():
    session = Session("t1")
    session.contextualize("Do you ship internationally?")
    query, rewritten = session.contextualize("What about Canada, and how long does it take?")
    assert rewritten is True
    assert "internationally" in query
    assert "Canada" in query


def test_first_message_is_never_rewritten():
    session = Session("t2")
    query, rewritten = session.contextualize("Do you ship internationally?")
    assert rewritten is False
    assert query == "Do you ship internationally?"


def test_order_id_is_remembered_for_a_followup():
    session = Session("t3")
    session.contextualize("Where is ORD-1007?")
    assert session.last_order_id == "ORD-1007"
    session.contextualize("When will it arrive?")
    assert session.facts("When will it arrive?") == {
        "order_id_mentioned_earlier_in_this_session": "ORD-1007"
    }


def test_order_id_is_not_offered_for_an_unrelated_question():
    session = Session("t4")
    session.contextualize("Where is ORD-1007?")
    assert session.facts("Are your tumblers dishwasher safe?") == {}


def test_sessions_do_not_share_state():
    store = SessionStore()
    first = store.get("a")
    second = store.get("b")
    first.contextualize("Where is ORD-1007?")
    assert second.last_order_id is None
    assert second.turns == []
    assert second.is_followup("What about it?") is False


def test_history_is_bounded():
    session = Session("t5", max_turns=2)
    for index in range(10):
        session.add_user("message {0}".format(index))
        session.add_assistant("reply {0}".format(index))
    assert len(session.history()) == 4
