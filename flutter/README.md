# flutter_hbb

A new Flutter project.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Lab: Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Cookbook: Useful Flutter samples](https://docs.flutter.dev/cookbook)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples and guidance on mobile development, and a full API reference.

## RDP from Linux

On Ubuntu 22.04, install `freerdp2-dev` before building the Linux desktop
client to include RDP support. The built client uses the system
`libfreerdp2-2` and `libwinpr2-2` libraries.

Enable Remote Desktop on the Windows host. In RustDesk, open the menu
next to **Connect** and choose **RDP**. Enter the Windows host name or IP
address, port (3389 by default), and Windows account credentials. For a
domain account, enter the username as `DOMAIN\username` or `user@example.com`.
The RDP session opens in a RustDesk window.
