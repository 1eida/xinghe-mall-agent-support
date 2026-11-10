import asyncio
import os
import urllib.parse
import uuid
from collections.abc import AsyncGenerator

import streamlit as st
from dotenv import load_dotenv
from streamlit.delta_generator import DeltaGenerator

from client import AgentClient, AgentClientError
from schema import ChatMessage

APP_TITLE = "电商智能客服与工单助手"
APP_ICON = "🧰"
USER_ID_COOKIE = "user_id"


def get_or_create_user_id() -> str:
    """Get the user ID from session state or URL parameters, or create a new one if it doesn't exist."""
    # Check if user_id exists in session state
    if USER_ID_COOKIE in st.session_state:
        return st.session_state[USER_ID_COOKIE]

    # Try to get from URL parameters using the new st.query_params
    if USER_ID_COOKIE in st.query_params:
        user_id = st.query_params[USER_ID_COOKIE]
        st.session_state[USER_ID_COOKIE] = user_id
        return user_id

    # Generate a new user_id if not found
    user_id = str(uuid.uuid4())

    # Store in session state for this session
    st.session_state[USER_ID_COOKIE] = user_id

    # Also add to URL parameters so it can be bookmarked/shared
    st.query_params[USER_ID_COOKIE] = user_id

    return user_id


async def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon=APP_ICON,
        menu_items={},
    )

    # Hide the streamlit upper-right chrome
    st.html(
        """
        <style>
        [data-testid="stStatusWidget"] {
                visibility: hidden;
                height: 0%;
                position: fixed;
            }
        </style>
        """,
    )
    if st.get_option("client.toolbarMode") != "minimal":
        st.set_option("client.toolbarMode", "minimal")
        await asyncio.sleep(0.1)
        st.rerun()

    # Get or create user ID
    user_id = get_or_create_user_id()

    if "agent_client" not in st.session_state:
        load_dotenv()
        agent_url = os.getenv("AGENT_URL")
        if not agent_url:
            host = os.getenv("HOST", "0.0.0.0")
            port = os.getenv("PORT", 8080)
            agent_url = f"http://{host}:{port}"
        try:
            with st.spinner("Connecting to agent service..."):
                st.session_state.agent_client = AgentClient(base_url=agent_url)
        except AgentClientError as e:
            st.error(f"Error connecting to agent service at {agent_url}: {e}")
            st.markdown("The service might be booting up. Try again in a few seconds.")
            st.stop()
    agent_client: AgentClient = st.session_state.agent_client
    if agent_client.info is None:
        st.error("Error connecting to agent service: service metadata is unavailable.")
        st.stop()

    if "thread_id" not in st.session_state:
        initial_messages: list[ChatMessage] = []
        thread_id = st.query_params.get("thread_id")
        if not thread_id:
            thread_id = str(uuid.uuid4())
        else:
            try:
                initial_messages = agent_client.get_history(thread_id=thread_id).messages
            except AgentClientError:
                st.error("No message history found for this Thread ID.")
        st.session_state.messages = initial_messages
        st.session_state.thread_id = thread_id

    # Config options
    with st.sidebar:
        st.header(f"{APP_ICON} {APP_TITLE}")

        st.write("查询商城政策、订单与退款资格，确认后创建客服工单。")

        if st.button(":material/chat: New Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.thread_id = str(uuid.uuid4())
            st.rerun()

        use_streaming = st.toggle("Stream results", value=True)

        @st.dialog("Share/resume chat")
        def share_chat_dialog() -> None:
            # Use Streamlit's public request context. The former implementation
            # reached into private session internals, which changed in Streamlit
            # 1.58 and caused an AttributeError when opening this dialog.
            try:
                current_url = str(st.context.url)
            except Exception:
                current_url = os.getenv("STREAMLIT_PUBLIC_URL", "http://127.0.0.1:8501")
            parsed_url = urllib.parse.urlsplit(current_url)
            st_base_url = urllib.parse.urlunsplit(
                (parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", "")
            )
            # if it's not localhost, switch to https by default
            is_local = parsed_url.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}
            if not st_base_url.startswith("https") and not is_local:
                st_base_url = st_base_url.replace("http", "https")
            # Include both thread_id and user_id in the URL for sharing to maintain user identity
            chat_url = (
                f"{st_base_url}?thread_id={st.session_state.thread_id}&{USER_ID_COOKIE}={user_id}"
            )
            st.markdown(f"**Chat URL:**\n```text\n{chat_url}\n```")
            st.info("Copy the above URL to share or revisit this chat")

        if st.button(":material/upload: Share/resume chat", use_container_width=True):
            share_chat_dialog()

        st.markdown("[项目源码](https://github.com/sooont/xinghe-mall-agent-support)")

    # Draw existing messages
    messages: list[ChatMessage] = st.session_state.messages

    if len(messages) == 0:
        welcome = """你好！我是电商智能客服演示助手。
        我可以查询政策、订单和退款资格，并在你确认后创建客服工单。
        你可以先试试：查询订单 ORD1001，手机号后四位 8821"""

        with st.chat_message("ai"):
            st.write(welcome)

    # draw_messages() expects an async iterator over messages
    async def amessage_iter() -> AsyncGenerator[ChatMessage, None]:
        for m in messages:
            yield m

    await draw_messages(amessage_iter())

    user_input = st.chat_input()

    if user_input:
        messages.append(ChatMessage(type="human", content=user_input))
        st.chat_message("human").write(user_input)
        try:
            if use_streaming:
                stream = agent_client.astream(
                    message=user_input,
                    thread_id=st.session_state.thread_id,
                    user_id=user_id,
                )
                await draw_messages(stream, is_new=True)
            else:
                response = await agent_client.ainvoke(
                    message=user_input,
                    thread_id=st.session_state.thread_id,
                    user_id=user_id,
                )
                messages.append(response)
                with st.chat_message("ai"):
                    st.write(response.content)
            st.rerun()  # Clear stale containers
        except AgentClientError as e:
            st.error(f"Error generating response: {e}")
            st.stop()


async def draw_messages(
    messages_agen: AsyncGenerator[ChatMessage | str, None],
    is_new: bool = False,
) -> None:
    """
    Draws a set of chat messages - either replaying existing messages
    or streaming new ones.

    This function has additional logic to handle streaming tokens and tool calls.
    - Use a placeholder container to render streaming tokens as they arrive.
    - Use a status container to render tool calls. Track the tool inputs and outputs
      and update the status container accordingly.

    The function also needs to track the last message container in session state
    since later messages can draw to the same container.

    Args:
        messages_aiter: An async iterator over messages to draw.
        is_new: Whether the messages are new or not.
    """

    # Keep track of the last message container
    last_message_type = None
    last_message: DeltaGenerator | None = None

    # Placeholder for intermediate streaming tokens
    streaming_content = ""
    streaming_placeholder = None

    # A tool call is normally followed immediately by a ToolMessage. HITL is the
    # important exception: the graph emits an interrupt/approval message first,
    # and the ToolMessage arrives only after the user resumes the run. Keep that
    # non-tool message here so the outer loop can render it normally.
    pending_msg: ChatMessage | str | None = None

    # Iterate over the messages and draw them
    while True:
        if pending_msg is not None:
            msg = pending_msg
            pending_msg = None
        else:
            msg = await anext(messages_agen, None)
        if msg is None:
            break

        # str message represents an intermediate token being streamed
        if isinstance(msg, str):
            # If placeholder is empty, this is the first token of a new message
            # being streamed. We need to do setup.
            if not streaming_placeholder:
                if last_message_type != "ai" or last_message is None:
                    last_message_type = "ai"
                    last_message = st.chat_message("ai")
                with last_message:
                    streaming_placeholder = st.empty()

            streaming_content += msg
            streaming_placeholder.write(streaming_content)
            continue
        if not isinstance(msg, ChatMessage):
            st.error(f"Unexpected message type: {type(msg)}")
            st.write(msg)
            st.stop()

        match msg.type:
            # A message from the user, the easiest case
            case "human":
                last_message_type = "human"
                st.chat_message("human").write(msg.content)

            # A message from the agent is the most complex case, since we need to
            # handle streaming tokens and tool calls.
            case "ai":
                # If we're rendering new messages, store the message in session state
                if is_new:
                    st.session_state.messages.append(msg)

                # If the last message type was not AI, create a new chat message
                if last_message_type != "ai" or last_message is None:
                    last_message_type = "ai"
                    last_message = st.chat_message("ai")

                with last_message:
                    # If the message has content, write it out.
                    # Reset the streaming variables to prepare for the next message.
                    if msg.content:
                        if streaming_placeholder:
                            streaming_placeholder.write(msg.content)
                            streaming_content = ""
                            streaming_placeholder = None
                        else:
                            st.write(msg.content)

                    if msg.tool_calls:
                        # Create a status container for each tool call and store the
                        # status container by ID to ensure results are mapped to the
                        # correct status container.
                        call_results = {}
                        for tool_call in msg.tool_calls:
                            status = st.status(
                                f"""🛠️ Tool Call: {tool_call["name"]}""",
                                state="running" if is_new else "complete",
                            )
                            call_results[tool_call["id"]] = status

                        # Expect one ToolMessage for each tool call.
                        for tool_call in msg.tool_calls:
                            status = call_results[tool_call["id"]]
                            status.write("Input:")
                            status.write(tool_call["args"])
                            tool_result = await anext(messages_agen, None)

                            if (
                                not isinstance(tool_result, ChatMessage)
                                or tool_result.type != "tool"
                            ):
                                status.write("等待用户确认，请在下方输入“确认”或“取消”。")
                                status.update(
                                    label=f"⏸️ Waiting for approval: {tool_call['name']}",
                                    state="complete",
                                )
                                # The interrupt prompt belongs to the normal message
                                # stream; do not swallow it while looking for a tool
                                # result.
                                pending_msg = tool_result
                                break

                            # Record the message if it's new, and update the correct
                            # status container with the result
                            if is_new:
                                st.session_state.messages.append(tool_result)
                            if tool_result.tool_call_id:
                                status = call_results[tool_result.tool_call_id]
                            status.write("Output:")
                            status.write(tool_result.content)
                            status.update(state="complete")

            # After an HITL resume, LangGraph may emit the ToolMessage without
            # repeating the earlier AI tool-call message in this HTTP stream.
            # Render it as a standalone result instead of treating it as invalid.
            case "tool":
                if is_new:
                    st.session_state.messages.append(msg)

                if last_message_type != "ai" or last_message is None:
                    last_message_type = "ai"
                    last_message = st.chat_message("ai")

                with last_message:
                    status = st.status("🛠️ Tool result", state="complete")
                    status.write("Output:")
                    status.write(msg.content)

            # In case of an unexpected message type, log an error and stop
            case _:
                st.error(f"Unexpected ChatMessage type: {msg.type}")
                st.write(msg)
                st.stop()


if __name__ == "__main__":
    asyncio.run(main())
