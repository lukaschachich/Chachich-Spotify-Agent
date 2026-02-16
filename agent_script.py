import os
import subprocess
import requests
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.graph import MessagesState
import asyncio
from mcp_use.client import MCPClient
from mcp_use.adapters.langchain_adapter import LangChainAdapter


# Ensure working directory is the script's own folder
os.chdir(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()  # loads variables from .env



# ------------ CHECKING CREDENTIALS ------------ #
# Check Spotify API credentials

def check_spotify_credentials():
    """
    Check if Spotify API credentials are valid by attempting to get an access token.
    Returns True if valid, False otherwise.
    """
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

    # Check if credentials exist
    if not all([client_id, client_secret, redirect_uri]):
        print("❌ Missing Spotify credentials in .env file")
        return False

    # Test credentials by requesting a client credentials token
    auth_url = "https://accounts.spotify.com/api/token"
    auth_headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    auth_data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }

    try:
        response = requests.post(auth_url, headers=auth_headers, data=auth_data)
        if response.status_code == 200:
            print("✅ Spotify credentials are valid")
            return True
        else:
            print(f"❌ Spotify credentials invalid. Status: {response.status_code}")
            print(f"Response: {response.json()}")
            return False
    except Exception as e:
        print(f"❌ Error checking Spotify credentials: {e}")
        return False


# Check Groq API credentials

def check_groq_credentials():
    """
    Check if Groq API credentials are valid.
    Returns True if valid, False otherwise.
    """
    groq_api_key = os.getenv("GROQ_API_KEY")

    if not groq_api_key:
        print("❌ Missing Groq API key in .env file")
        return False

    # Example pattern – adjust URL / headers based on Groq's docs
    test_url = "https://api.groq.com/openai/v1/models"
    headers = {
        "Authorization": f"Bearer {groq_api_key}"
    }

    try:
        response = requests.get(test_url, headers=headers)
        if response.status_code == 200:
            print("✅ Groq credentials are valid")
            return True
        else:
            print(f"❌ Groq credentials invalid. Status: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error checking Groq credentials: {e}")
        return False


def kill_processes_on_port(port):
    """Kill processes on Windows"""
    try:
        # Find processes using the port
        result = subprocess.run(['netstat', '-ano'],
                              capture_output=True, text=True, check=False)

        if result.returncode == 0:
            lines = result.stdout.split('\n')
            pids_to_kill = []

            for line in lines:
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]  # Last column is PID
                        if pid.isdigit():
                            pids_to_kill.append(pid)

            if pids_to_kill:
                print(f"Found processes on port {port}: {pids_to_kill}")
                for pid in pids_to_kill:
                    try:
                        subprocess.run(['taskkill', '/F', '/PID', pid],
                                     check=True, capture_output=True)
                        print(f"Killed process {pid} on port {port}")
                    except subprocess.CalledProcessError as e:
                        print(f"Failed to kill process {pid}: {e}")
            else:
                print(f"No processes found on port {port}")
        else:
            print(f"Failed to run netstat: {result.stderr}")

    except Exception as e:
        print(f"Error killing processes on port {port}: {e}")

async def create_graph():
    #create client
    client = MCPClient.from_config_file("mcp_config.json")

    #create adapter instance
    adapter = LangChainAdapter()

    #load in tools from the MCP client
    tools = await adapter.create_tools(client)
    tools = [t for t in tools if t.name not in['getNowPlaying', 'getRecentlyPlayed', 'getQueue', 'playMusic', 'pausePlayback', 'skipToNext', 'skipToPrevious', 'resumePlayback', 'addToQueue', 'getMyPlaylists','getUsersSavedTracks', 'saveOrRemoveAlbum', 'checkUsersSavedAlbums']]

    #define llm
    llm = ChatGroq(model='llama-3.1-8b-instant')

    #bind tools
    llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)


    system_msg = """
    You are a Spotify AI assistant with access to Spotify tools.

    Your capabilities include:
    - Creating playlists
    - Adding songs to playlists
    - Searching for songs, artists, and albums
    - Providing personalized music recommendations
    - Curating well-structured playlists with thoughtful descriptions

    General Behavior Guidelines:
    - Be concise but helpful.
    - Ask clarifying questions if the user’s request is ambiguous.
    - Use tools whenever an action needs to be performed on Spotify.
    - Do NOT hallucinate playlist creation — always call the proper tool.
    - Only respond with final answers after confirming tool success.

    When Creating Playlists:
    - If the user does not specify playlist size, limit it to 10 songs.
    - If the user specifies a number greater than 20, limit it to 20.
    - Always ensure songs are actually added to the playlist.
    - Curate cohesive playlists (genre, mood, theme consistency).
    - Provide a short, creative playlist description.
    - Avoid duplicate songs.

    When Giving Recommendations:
    - Base recommendations on:
    - Mood (e.g., happy, chill, gym, study)
    - Genre preferences
    - Specific artists the user likes
    - Era (e.g., 90s hip-hop, 2010s pop)
    - Explain briefly why songs were selected.

    Error Handling:
    - If a tool fails, inform the user clearly.
    - If required information is missing (e.g., playlist name), ask for it.
    - If a requested song cannot be found, suggest alternatives.

    Always prioritize accuracy, clean execution, and thoughtful music curation.
    """

    #define assistant
    def assistant(state: MessagesState):
        return {"messages": [llm_with_tools.invoke([system_msg] + state["messages"])]}

    # Graph
    builder = StateGraph(MessagesState)

    # Define nodes: these do the work
    builder.add_node("assistant", assistant)
    builder.add_node("tools", ToolNode(tools))

    # Define edges: these determine the control flow
    builder.add_edge(START, "assistant")
    builder.add_conditional_edges(
       "assistant",
        tools_condition,
    )
    builder.add_edge("tools", "assistant")

    graph = builder.compile()
    return graph



async def invoke_our_graph(agent, st_messages):
    response = await agent.ainvoke({"messages": st_messages})
    return response

async def main():
    print("Checking API credentials...\n")

    spotify_valid = check_spotify_credentials()
    groq_valid = check_groq_credentials()

    print("\nCredentials Summary:")
    print(f"Spotify: {'✅ Valid' if spotify_valid else '❌ Invalid'}")
    print(f"Groq: {'✅ Valid' if groq_valid else '❌ Invalid'}")

    if spotify_valid and groq_valid:
        print("\n🎉 All credentials are working!")
    else:
        print("\n⚠️ Please fix invalid credentials before proceeding.")

    # Kill any leftover processes on port 8090
    kill_processes_on_port(8090)

    # Only start the agent if credentials are valid
    agent = await create_graph()

    
    while True:
        message = input("User: ")

        if message.lower() in ["exit", "quit"]:
            print("Goodbye!")
            break

        response = await invoke_our_graph(agent, [{"role": "user", "content": message}])

        print("Assistant:", response["messages"][-1].content)



if __name__ == "__main__":
    # Run the main function in an asyncio event loop
    asyncio.run(main())  
    
# ------------ END OF CREDENTIALS CHECK ------------ #
