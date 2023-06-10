# lumix-upnp-dump

Program that dumps media from Lumix cameras on the network, removing them from the device.
Allows to automatically dump all media from the camera, including videos, not limited by the number of files being dumped.
**Once media are transferred to the computer, they're deleted from the camera.**


## ⚠️ Warranty

**This software comes with no warranty whatsoever.**
Take note your photos might get unrecoverably deleted or camera might misbehave.
You're using this on your own risk and responsibility.


## Installation

Requires python3.10.

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

