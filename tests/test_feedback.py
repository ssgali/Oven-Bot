from oven_bot.feedback import classify_feedback
from oven_bot.models import FeedbackAction


def test_feedback_routes_to_render():
    assert classify_feedback("Make the lighting brighter and change the angle") is FeedbackAction.RERENDER


def test_feedback_routes_to_edit():
    assert classify_feedback("The CTA text is too small") is FeedbackAction.REEDIT


def test_feedback_routes_to_approval():
    assert classify_feedback("approved, looks good") is FeedbackAction.APPROVE
