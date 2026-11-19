#ifndef RUSTDESK_RDP_CHANNEL_H_
#define RUSTDESK_RDP_CHANNEL_H_

#include <flutter_linux/flutter_linux.h>
#include <gtk/gtk.h>

bool handle_rdp_call(GtkApplication* app, FlMethodCall* call);

#endif
