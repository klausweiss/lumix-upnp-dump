# lumix-upnp-dump

Program that dumps media from Lumix cameras on the network, removing them from the device.
Allows to automatically dump all media from the camera, including videos, not limited by the number of files being dumped.
**Once media are transferred to the computer, they're deleted from the camera.**



> [!CAUTION]
> **This software comes with no warranty whatsoever.**
> Take note your photos might get unrecoverably deleted or camera might misbehave.
> You're using this on your own risk and responsibility.


## Installation

Requires python3.10.

Saving videos requires `ffmpeg` to be installed as well.

```shell
pipx install lumix-upnp-dump
```

## Supported cameras

The table below shows cameras which have been tested with this software.
It can potentially support other models as well.

| Model | Dumps JPEG | Dumps videos | Dumps RAW | Notes |
| ----- | ---------- | ------------ | --------- | ----- |
| GX7   | ✅         | ✅           | ❌        | RAW images are dumped as JPEGs |
| GX800 | ✅         | ✅           | ✅        |                                |
| G80   | ✅         | ✅           | ✅        | Needs an additional one-time setup step. Connect to the real Panasonic Image App first in the same network as the one you'll use `lumix-upnp-dump` in. After you disconnect and start `lumix-upnp-dump`, it should be able to connect to the camera. |


## Usage

1. Run the program with

    ```shell
    lumix-upnp-dump -o output/
    ```

2. Connect camera to the Wi-Fi network (see _Connecting via a wireless access point_ in the device manual), using _Remote shooting & view_ function. 
   The camera will ask you to launch the smartphone application upon successful connection. `lumix-upnp-dump` acts as the smartphone application, so if the program is running, there's nothing else you need to do.

3. The program iterates all Lumix cameras on the network. When a download from your camera starts, you'll see a prompt message on the camera screen - _Under remote control_.

4. After all media is dumped, the program will inform you by logging appropriate information, but **the camera connection will not close**.
   The screen on your camera will be black all this time.
   It's easy to forget the camera is runnng and drain the battery this way.
   You can interrupt the connection on the camera now by half-pressing the shutter button and turning the camera off or terminating the network connection (see the device manual).

### Full help text


> [!WARNING]
> Be careful what you put in `--command-after-finish`.
> It uses python's `subprocess.run` under the hood, hence allows to execute arbitraty code.

```
usage: lumix-upnp-dump [-h] [-c CONFIG_FILE] -o OUTPUT_DIR [--command-after-finish COMMAND_AFTER_FINISH]

options:
  -h, --help            show this help message and exit
  -c CONFIG_FILE, --config-file CONFIG_FILE
                        Config file path
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Directory where the photos should be saved
  --command-after-finish COMMAND_AFTER_FINISH
                        A shell command to run when downloading media from a camera is finished. Also run if
                        downloading was interrupted. The command can include the following special tags which will be
                        replaced by appropriate values when run:
                          - ${camera}: the camera name
                          - ${n}: number of media files fetched (a picture is only counted once even if both JPEG and
                            RAW were saved)
                          - ${total}: total number of media files on the device prior to download or '-' if unknown
                        For example:

                          lumix-upnp-dump [...] --command-after-finish 'echo Downloaded ${n}/${total} media files from
                          ${camera} >> /tmp/lumix-dump.log'

Args that start with '--' can also be set in a config file (specified via -c). Config file syntax is Tom's Obvious,
Minimal Language. See https://github.com/toml-lang/toml/blob/v0.5.0/README.md for details. In general, command-line
values override config file values which override defaults.
```

### NixOS installation

> [!NOTE]
> NixOS support is experimental. I'm only starting to learn it, all feedback is appreciated.
