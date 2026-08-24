# Demo recording script

Target length: 2-4 minutes across both clips. One clip records the web page at http://127.0.0.1:8000, the other records the evaluation suite in a terminal. Both are embedded at the top of the README.

## 1. Knowledge-base answer with citations

    python -m src.agent.cli

    you > How long do I have to return a backpack I did not use?
    you > I had TrailPlus active when I ordered. Does that change anything?

Point out the `Sources:` line and that the 45-day answer comes from the membership policy rather than the superseded 2024 policy.

## 2. Order lookup

    you > Where is ORD-1007 and when should it arrive?

Point out the status, carrier, and estimate, and that no email, address, or internal note appears.

## 3. Multi-turn

    you > Do you ship internationally?
    you > What about Canada, and how long does it take?

Point out that the follow-up is understood without repeating the topic.

## 4. Refusal and human handoff

    you > Can I put the entire Breeze Tumbler in the dishwasher?
    you > For ORD-1007, give me the customer's email and risk score.

Point out the surfaced source conflict, the refusal, and the handoff line.

## 5. Evaluation suite

    python -m src.eval.run --workers 3

Show the progress lines, the per-case results, and the category table at the end. Keep workers at 3 or below on a free-tier key so the run does not stall on rate limits.

## 6. Trace (optional)

    python -m src.agent.cli --debug --ask "When will ORD-1004 arrive?"

Show the retrieved passages with scores and the sanitized tool result.
