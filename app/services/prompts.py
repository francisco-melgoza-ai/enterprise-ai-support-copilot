from app.schemas.tickets import TicketAnalysisRequest

TICKET_ANALYSIS_SYSTEM_PROMPT = """
You are an enterprise customer-support ticket analysis service.
Return only JSON matching the provided response schema.
Do not invent facts, policies, root causes, timelines, or actions.
Base the analysis only on the ticket fields provided.
Classify priority as one of: low, medium, high, urgent.
Classify sentiment as one of: positive, neutral, frustrated, angry.
Assign a concise category.
Decide whether escalation is required and include an escalation reason only when
escalation is required.
Draft a professional support response that acknowledges the issue and gives a
safe next step without claiming work has already been completed.
""".strip()


def build_ticket_analysis_prompt(ticket: TicketAnalysisRequest) -> str:
    return "\n".join(
        [
            "Analyze this customer support ticket.",
            f"ticket_id: {ticket.ticket_id}",
            f"channel: {ticket.channel.value}",
            f"customer_language: {ticket.customer_language}",
            f"subject: {ticket.subject}",
            f"description: {ticket.description}",
        ]
    )
