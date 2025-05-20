from datetime import datetime
from mcp.server.fastmcp import FastMCP
from typing import Optional

# Create an MCP server
mcp = FastMCP("Modal Development Utils")

@mcp.tool()
def get_current_time() -> datetime:
    return datetime.now()

@mcp.tool(description="""
          Create a new sandbox in Modal and return the object ID and a list of tunnels.

          This sandbox has minimal installed packages so if you run into issues, you can always
          use modal_exec_in_sandbox to run a command in the sandbox to install packages.

          The tunnels are encrypted and can be used to access the sandbox from the outside.
          No other ports are accessible from the outside except for the ones specified in the returned tunnels.

          The sandbox will be terminated after 20 minutes of inactivity.

          If you create a sandbox after it has been terminated, the filesystem will be restored from 
          the last snapshot.

          The sandbox will be created with your local public key for ssh access. 
          You can use the ssh_host and ssh_port to connect to the sandbox.

          If you need to copy files to or from the sandbox, you can use rsync or scp as needed. This is convenient
          if you want to copy scripts, for instance temporary scripts.

          If you want to mount a local directory to the sandbox, you can do so by passing the path to the directory
          to the mount_dir argument.

          If you want to use a GPU, you can do so by passing the gpu argument - this can be one of:
          * 'T4'
          * 'L4'
          * 'A10G'
          * 'A100-40GB'
          * 'A100-80GB'
          * 'H100'
          * 'H200'
          * 'H100!' # Require H100 exactly, no other GPUs will do.

          You can choose the number of GPUs and pass that in the gpu argument by separating the gpu type and number of GPUs with a colon,
          for example 'T4:4' would create a sandbox with 4 T4 GPUs.

          See up to date information here: https://modal.com/docs/guide/gpu#gpu-acceleration

          Show the user an ssh command to connect to the sandbox as root user.
          """)
def modal_create_sandbox(timeout: int = 60 * 20, mount_dir: str = None, gpu: str = None) -> str:
    from modal import App, Sandbox, Image, Mount
    app = App.lookup("modal-sandbox", create_if_missing=True)
    # Read local public key
    import os
    from pathlib import Path
    
    home_dir = str(Path.home())
    ssh_key_path = os.path.join(home_dir, ".ssh", "id_ed25519.pub")
    
    with open(ssh_key_path, "r") as f:
        public_key = f.read().strip()

    image = (
        Image.debian_slim(python_version="3.11")
            .apt_install("git")
            .apt_install("openssh-server")
            .apt_install("rsync")
            .run_commands("mkdir -p /var/run/sshd")
            .run_commands("echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config")
            .run_commands("service ssh start")
            .run_commands("mkdir -p /root/.ssh && chmod 700 /root/.ssh")
            .run_commands(f"echo '{public_key}' >> /root/.ssh/authorized_keys")
            .run_commands("chmod 600 /root/.ssh/authorized_keys")
    )

    # Prepare mounts argument conditionally
    mounts_list = []
    if mount_dir:
        # os.path.basename is available via 'import os' used earlier for ssh key
        remote_dir_name = os.path.basename(mount_dir)
        # Construct remote_path as /<basename>.
        # If remote_dir_name is empty (e.g., mount_dir="/"), remote_path becomes "/".
        # If remote_dir_name is "." (e.g., mount_dir="."), remote_path becomes "/.".
        remote_path = f"/root/{remote_dir_name}"
        mounts_list = [Mount.from_local_dir(mount_dir, remote_path=remote_path)]

    sb = Sandbox.create(
        "/usr/sbin/sshd",
        "-D",
        "-e",
        "-p", "22",
        app=app, 
        image=image,
        gpu=gpu,
        mounts=mounts_list,
        encrypted_ports=[8000, 8001, 8002], 
        unencrypted_ports=[22],
        timeout=timeout)
    tunnels = sb.tunnels()
    ssh_tunnel = tunnels[22]
    ssh_host = ssh_tunnel.unencrypted_host
    ssh_port = ssh_tunnel.unencrypted_port
    # Remove the ssh tunnel from the list of tunnels.
    tunnels.pop(22)
    return {
        "sandbox_id": sb.object_id,
        "tunnels": {port: t.url for (port, t) in tunnels.items()},
        "ssh_host": ssh_host,
        "ssh_port": ssh_port
    }
   

@mcp.tool(description="""
          Restore a sandbox from a filesystem snapshot with the given image id.
          """)
async def modal_restore_sandbox(image_id: str) -> str:
    from modal import App, Sandbox, Image
    app = await App.lookup.aio("modal-sandbox", create_if_missing=True)
    sb = Sandbox.create(app=app, 
                        image=await Image.from_id.aio(image_id), # If this is None, works properly.
                        encrypted_ports=[8000, 8001, 8002], timeout=60 * 4)
    tunnels = await sb.tunnels.aio()
    return {
        "sandbox_id": sb.object_id,
        "tunnels": {port: t.url for (port, t) in tunnels.items()},
        "image_id": image_id
    }


@mcp.tool(description="""
          Terminate a sandbox.
          """)
async def modal_terminate_sandbox(sandbox_id: str):
    from modal import App, Sandbox
    sb = await Sandbox.from_id.aio(sandbox_id)
    await sb.terminate.aio()


@mcp.tool(description="""
          Check the status of a sandbox. Returns the exit code of the sandbox if it has terminated.
          """)
async def modal_check_sandbox_status(sandbox_id: str) -> Optional[int]:
    from modal import App, Sandbox
    sb = await Sandbox.from_id.aio(sandbox_id)
    exit_code = await sb.poll.aio()
    return exit_code


@mcp.tool(description="""
          Execute a command in a sandbox.  
          
          The command must be separated into a list of strings. E.g. ['ls', '-l', '/']
          Note that this is akin to runsc exec, not executing a bash command. 
          If you want statefulness across exec commands, you need to track that state manually.
          E.g. if you want to cd to a directory and then run a command, you need to cd to the directory 
          in the same exec call, or otherwise find a way to track the state.

          Note also that exec commands are synchronous and run in the foreground, so if you start a long running process,
          you will need to wait for it to finish before modal_exec_in_sandbox can return.

          If you want to run a command in the background, you can use modal_exec_in_sandbox_background.

          If you don't want to save the image after the exec call, you can set save_image_after_exec to False.

          If you pass save_image_after_exec=True, the filesystem is saved after
          the exec call, so if the sandbox times out and needs to be recreated,
          there is no need to install packages or rerun commands that affect the
          filesystem state - you can just restore the sandbox from the last snapshot.

          The image id returned is the id of the filesystem snapshot after the command is run.
          You can use this image id to restore the sandbox to a previous state.
          """)
async def modal_exec_in_sandbox(sandbox_id: str, command: list[str], save_image_after_exec: bool = True) -> tuple[int, str, str, str]:
    """
    Execute a command in a sandbox and return the exit code, stdout, and stderr.

    Args:
        sandbox_id: The ID of the sandbox to execute the command in.
        command: A command separated into a list of strings. E.g. ['ls', '-l', '/']
        save_image_after_exec: Whether to save the image after the command is run. Do this when 
                               the executed command modifies the filesystem state.

    Returns:
        A tuple containing the exit code, stdout, and stderr of the command, and the image id after the command is run.
    """
    from modal import App, Sandbox
    sb = await Sandbox.from_id.aio(sandbox_id)
    p = await sb.exec.aio(*command)
    await p.wait.aio()
    if save_image_after_exec:
        image_id = (await sb.snapshot_filesystem.aio()).object_id
    else:
        image_id = None

    return p.returncode, await p.stdout.read.aio(), await p.stderr.read.aio(), image_id

executing_processes = {}

@mcp.tool(description="""
          Execute a command in a sandbox in the background. Use this for long running processes 
          that you don't want to wait for immediately, like a web server. For short running processes,
          use modal_exec_in_sandbox.
          
          The command must be separated into a list of strings. E.g. ['ls', '-l', '/']
          Note that this is akin to runsc exec, not executing a bash command. 
          If you want statefulness across exec commands, you need to track that state manually.
          E.g. if you want to cd to a directory and then run a command, you need to cd to the directory 
          in the same exec call, or otherwise find a way to track the state. 

          The command will be executed in the background and an id will be returned.
          You can use this process ID to wait for the process later or to check its status.
          This is not the linux process id, but a unique id assigned by the MCP server.

          The image id returned is the id of the filesystem snapshot after the command is run.
          You can use this image id to restore the sandbox to a previous state.
          """)
async def modal_exec_in_sandbox_background(sandbox_id: str, command: list[str]) -> int:
    """
    Execute a command in a sandbox and return the process ID.

    Args:
        sandbox_id: The ID of the sandbox to execute the command in.
        command: A command separated into a list of strings. E.g. ['ls', '-l', '/']

    Returns:
        The process ID which can be used to wait for the process to finish.
    """
    from modal import App, Sandbox
    sb = await Sandbox.from_id.aio(sandbox_id)
    p = await sb.exec.aio(*command)
    process_id = len(executing_processes) + 1
    executing_processes[process_id] = p
    return process_id


@mcp.tool(description="""
          Wait for a process in a sandbox and return the exit code, stdout, and stderr.
          """)
async def modal_wait_for_process(sandbox_id: str, process_id: int) -> tuple[int, str, str, str]:
    from modal import App, Sandbox
    sb = await Sandbox.from_id.aio(sandbox_id)
    p = executing_processes.pop(process_id)
    await p.wait.aio()

    return p.returncode, await p.stdout.read.aio(), await p.stderr.read.aio()

if __name__ == "__main__":
    mcp.run()

# TODO: Add a way to kill process.
# TODO: Local directory syncing