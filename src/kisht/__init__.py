"""Kisht: an EMI repayment agent for Indian lenders (voice + chat, Hindi/English).

Layout (ports and adapters):
  kisht.ports      interfaces the core depends on (chat model, call state)
  kisht.adapters   swappable implementations (local/cloud LLM servers, Redis, ...)
  kisht.config     config.yaml -> which adapter plays which role
"""
