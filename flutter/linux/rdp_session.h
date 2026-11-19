#ifndef RUSTDESK_RDP_SESSION_H_
#define RUSTDESK_RDP_SESSION_H_

#include <gtk/gtk.h>

extern "C" gboolean rustdesk_rdp_open(GtkApplication* app, const char* host,
                                      unsigned port, const char* username,
                                      const char* password);

#endif
