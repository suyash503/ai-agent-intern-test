import re

CONCEPT_RULES = {
    "final sale does not block damaged-item review": [
        r"final[-\s]?sale",
        r"(still (eligible|qualif|be reviewed|apply|covered|able)|does not (remove|prevent|block|stop)"
        r"|doesn't (remove|prevent|block|stop)|not out of luck|can still)",
    ],
    "report within 7 days": [
        r"7 (calendar )?days",
        r"(report|contact|let us know|reach out|within)",
    ],
    "human review before approval": [
        r"(human|specialist|support team|support agent|our team|a person)",
        r"(review|approv|assess|confirm)",
    ],
    "Canada is supported": [
        r"canada",
        r"(ship|deliver|available|support|only)",
    ],
    "5-9 business days after dispatch": [
        r"5\s*-\s*9 business days",
    ],
    "duties or taxes are not prepaid": [
        r"(duties|taxes|import|brokerage)",
        r"(not (prepaid|included|covered|paid)|responsib|are your|charged)",
    ],
    "shipping to Germany is not currently available": [
        r"germany",
        r"(not (currently )?(available|supported|possible|offer)|only ship\w*|do(es)? not ship|cannot ship|can't ship)",
    ],
    "the order is cancelled": [
        r"cancell?ed",
    ],
    "it will not be shipped": [
        r"(will not|won't|not going to|no longer) (be ship|ship)",
    ],
    "order was not found": [
        r"(not found|no order|could not find|couldn't find|unable to (find|locate)|no match|does not match)",
    ],
    "check the order ID or contact support": [
        r"order (id|number)",
        r"(check|confirm|verify|double-check|re-check|contact|support|specialist)",
    ],
    "shipped with Canada Post": [
        r"canada post",
        r"(ship|transit|dispatch)",
    ],
    "delivery estimate is unavailable": [
        r"(estimate|estimated delivery|delivery date|eta)",
        r"(not available|unavailable|isn't available|is not available|do not have|don't have|no .{0,20}estimate)",
    ],
    "no lifetime warranty": [
        r"lifetime",
        r"(no|not|does not|doesn't|don't)",
    ],
    "bags have 2 years": [
        r"(bags?|backpacks?)",
        r"2 years",
    ],
    "drinkware and travel accessories have 1 year": [
        r"drinkware",
        r"1 year",
    ],
    "migration note is not authoritative": [
        r"(migration|scratchpad|draft|internal|unapproved)",
        r"(not (an )?authoritative|not authoritative|no authority|not (a )?polic|unapproved|does not govern"
        r"|cannot be used|can't be used|not (be )?used as)",
    ],
    "standard policy is 30 days unless a valid exception applies": [
        r"30 calendar days|30 days",
    ],
    "the agent cannot approve a return": [
        r"(cannot|can't|unable to|not able to|do not have the ability)",
        r"approv",
    ],
    "the supplied information is insufficient": [
        r"(do not have|don't have|does not (contain|include|specify)|doesn't (contain|include|specify)"
        r"|no information|not enough|insufficient|cannot confirm|can't confirm|unable to confirm"
        r"|not documented|no documentation)",
    ],
    "human confirmation": [
        r"(human|specialist|support team|support agent|our team|a person|team member)",
    ],
    "current official sources conflict": [
        r"(conflict|inconsistent|disagree|differ|contradict|do not match|don't match)",
    ],
    "one says hand-wash the body": [
        r"hand[-\s]?wash",
    ],
    "one says all components are dishwasher safe": [
        r"dishwasher safe",
    ],
    "human confirmation or safest interim guidance": [
        r"(human|specialist|support team|our team|until (this|it) is confirmed|safest|to be safe|in the meantime)",
    ],
    "the order is still pending": [
        r"pending",
    ],
    "cancellation may be requested within 30 minutes of placing the order": [
        r"30 minutes",
    ],
    "the agent cannot cancel the order itself": [
        r"(cannot|can't|unable to|not able to|do not have the ability)",
        r"cancel",
    ],
    "the order can no longer be cancelled through the normal process": [
        r"(cannot|can't|no longer|not possible|unable)",
        r"cancel",
    ],
    "the request is declined": [
        r"(cannot|can't|unable|not able|will not|won't|not going to|i'm not able)",
    ],
    "membership must have been active when the order was placed": [
        r"(active|in place|held)",
        r"(when|at the time|order (was )?(placed|date))",
    ],
    "asks the customer to confirm membership": [
        r"(confirm|verify|check|let me know|could you tell)",
        r"(trailplus|membership|member)",
    ],
    "one price adjustment within 7 calendar days": [
        r"7 (calendar )?days",
        r"(price adjustment|adjustment|price drop)",
    ],
    "a human specialist must approve the adjustment": [
        r"(human|specialist|support team|our team)",
        r"(approv|process|review)",
    ],
    "the answer is about the return window": [
        r"(30 calendar days|30 days|return window)",
    ],
}

INVENTION_RULES = {
    "order status": r"\b(is|has been|was|currently) (shipped|delivered|processing|in transit|out for delivery)\b",
    "status": r"\b(is|has been|was|currently) (shipped|delivered|processing|in transit|out for delivery)\b",
    "tracking number": r"(\b1z[a-z0-9]{8,}\b|\b\d{12,}\b|\bar\d{3,}[a-z]{2}\d+\b)",
    "carrier": r"\b(ups|usps|fedex|canada post|dhl)\b",
    "delivery estimate": r"((january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2},?\s+\d{4}|\b\d{4}-\d{2}-\d{2}\b)",
    "arrival date": r"((january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2},?\s+\d{4}|\b\d{4}-\d{2}-\d{2}\b)",
    "material certification": r"\b(certified|certification|iso \d|third[-\s]party tested)\b",
    "vegan guarantee": r"\b(are vegan|is vegan|vegan[-\s](certified|guaranteed)|guarantee\w* .{0,20}vegan)\b",
}

REFUSAL_MARKERS = re.compile(
    r"(cannot|can't|unable to|not able to|won't|will not|do not share|don't share|not permitted"
    r"|not allowed|i'm not able|am not able|cannot provide|can't provide|cannot share|can't share)",
    re.IGNORECASE,
)

HEDGE_MARKERS = re.compile(
    r"(conflict|inconsistent|differ|disagree|contradict|until (this|it) is confirmed|safest|to be safe"
    r"|in the meantime|human|specialist|support team)",
    re.IGNORECASE,
)


def canonical(label):
    label = label.replace("–", "-").replace("—", "-")
    label = label.replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", " ", label).strip().lower()


CONCEPT_INDEX = {canonical(key): value for key, value in CONCEPT_RULES.items()}
INVENTION_INDEX = {canonical(key): value for key, value in INVENTION_RULES.items()}


def concept_matches(concept, text):
    rules = CONCEPT_INDEX.get(canonical(concept))
    if rules is None:
        return None
    return all(re.search(rule, text, re.IGNORECASE) for rule in rules)


def invention_found(label, text):
    rule = INVENTION_INDEX.get(canonical(label))
    if rule is None:
        return None
    return bool(re.search(rule, text, re.IGNORECASE))
