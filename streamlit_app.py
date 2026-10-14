"""Chat page for the dress rankings. The terminal command is still python agent.py."""

import re

import streamlit as st

from agent import answer_stream

st.set_page_config(page_title="chatbot agent")
st.title("chatbot agent")

if "messages" not in st.session_state:
    st.session_state.messages = []


def _urls(text: str) -> list[str]:
    found = re.findall(r"https?://[^\s)>\]]+", text)
    return [url.rstrip(".,;") for url in found]


def _is_image(url: str) -> bool:
    lowered = url.lower()
    return (
        "/image/" in lowered
        or "/is/image/" in lowered
        or lowered.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
    )


def _show(text: str) -> None:
    st.markdown(text)
    images = [url for url in _urls(text) if _is_image(url)]
    for url in images:
        st.image(url, width=280)


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        _show(message["content"])

question = st.chat_input("Ask about a dress")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        reply = st.write_stream(answer_stream(question))
        for url in _urls(reply):
            if _is_image(url):
                st.image(url, width=280)
    st.session_state.messages.append({"role": "assistant", "content": reply})
