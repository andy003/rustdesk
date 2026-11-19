#include "rdp_channel.h"

#include <dlfcn.h>

#include "rdp_session.h"

namespace {

decltype(&rustdesk_rdp_open) LoadRdp() {
  g_autofree char* executable = g_file_read_link("/proc/self/exe", nullptr);
  if (!executable) return nullptr;
  g_autofree char* directory = g_path_get_dirname(executable);
  g_autofree char* module =
      g_build_filename(directory, "lib", "librustdesk_rdp.so", nullptr);
  void* library = dlopen(module, RTLD_NOW | RTLD_LOCAL);
  if (!library) {
    g_debug("Embedded RDP could not be loaded: %s", dlerror());
    return nullptr;
  }
  auto open = reinterpret_cast<decltype(&rustdesk_rdp_open)>(
      dlsym(library, "rustdesk_rdp_open"));
  if (!open) dlclose(library);
  return open;
}

FlValue* Argument(FlValue* args, const char* key, FlValueType type) {
  if (!args || fl_value_get_type(args) != FL_VALUE_TYPE_MAP) return nullptr;
  FlValue* value = fl_value_lookup_string(args, key);
  return value && fl_value_get_type(value) == type ? value : nullptr;
}

}  // namespace

bool handle_rdp_call(GtkApplication* app, FlMethodCall* call) {
  if (g_strcmp0(fl_method_call_get_name(call), "connectRdp") != 0) return false;
  FlValue* args = fl_method_call_get_args(call);
  FlValue* host = Argument(args, "host", FL_VALUE_TYPE_STRING);
  FlValue* port = Argument(args, "port", FL_VALUE_TYPE_INT);
  FlValue* username = Argument(args, "username", FL_VALUE_TYPE_STRING);
  FlValue* password = Argument(args, "password", FL_VALUE_TYPE_STRING);
  if (!host || !port || !username || !password || !*fl_value_get_string(host) ||
      !*fl_value_get_string(username) || fl_value_get_int(port) < 1 ||
      fl_value_get_int(port) > 65535) {
    fl_method_call_respond_error(call, "invalid-rdp-settings",
                                 "Invalid RDP connection settings.", nullptr,
                                 nullptr);
    return true;
  }

  static auto open = LoadRdp();
  if (!open) {
    fl_method_call_respond_error(
        call, "rdp-unavailable",
        "Embedded RDP or its FreeRDP 2 libraries are unavailable.", nullptr,
        nullptr);
  } else if (!open(app, fl_value_get_string(host), fl_value_get_int(port),
                   fl_value_get_string(username),
                   fl_value_get_string(password))) {
    fl_method_call_respond_error(call, "rdp-start-failed",
                                 "Could not start the RDP session.", nullptr,
                                 nullptr);
  } else {
    fl_method_call_respond_success(call, nullptr, nullptr);
  }
  return true;
}
