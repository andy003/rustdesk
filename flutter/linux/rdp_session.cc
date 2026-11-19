#include "rdp_session.h"

#include <freerdp/freerdp.h>
#include <freerdp/gdi/gdi.h>
#include <freerdp/input.h>
#include <freerdp/locale/keyboard.h>
#include <winpr/input.h>
#include <winpr/synch.h>

#include <algorithm>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <vector>

namespace {

struct Input {
  enum Kind { Key, Mouse, ExtendedMouse, Sync } kind;
  UINT16 flags;
  UINT16 x = 0;
  UINT16 y = 0;

  bool Send(rdpInput* input) const {
    switch (kind) {
      case Key:
        return freerdp_input_send_keyboard_event_ex(input, flags, x);
      case Mouse:
        return freerdp_input_send_mouse_event(input, flags, x, y);
      case ExtendedMouse:
        return freerdp_input_send_extended_mouse_event(input, flags, x, y);
      case Sync:
        return freerdp_input_send_synchronize_event(input, flags);
    }
    return false;
  }
};

struct Frame {
  int width = 0;
  int height = 0;
  int stride = 0;
  std::vector<BYTE> data;
};

struct Viewport {
  double scale;
  double x;
  double y;
};

class Session {
 public:
  Session() : wake_(CreateEvent(nullptr, TRUE, FALSE, nullptr)) {}

  ~Session() {
    if (wake_) CloseHandle(wake_);
  }

  static bool Open(GtkApplication* app, const std::string& host, unsigned port,
                   std::string username, const char* password);

 private:
  struct Context {
    rdpContext rdp;
    Session* session;
  };

  void Run(const std::string& host, unsigned port, std::string username,
           const std::string& password, DWORD layout);
  void Finish(const std::string& message);
  bool ProcessInput(rdpInput* input);
  void Queue(Input input);
  void Stop();
  DWORD Verify(const char* fingerprint, bool host_mismatch);
  bool PublishFrame(rdpGdi* gdi);
  bool Tick();
  void Draw(cairo_t* cr);
  Viewport GetViewport() const;
  bool Point(double x, double y, bool clamp, UINT16& remote_x,
             UINT16& remote_y);
  void Button(const GdkEventButton& event);
  void Key(const GdkEventKey& event);
  void Focus(bool focused);
  void Scroll(const GdkEventScroll& event);

  static Session& From(rdpContext* context) {
    return *reinterpret_cast<Context*>(context)->session;
  }

  static BOOL Resize(rdpContext* context);
  static BOOL PostConnect(freerdp* client);

  GtkWidget* window_ = nullptr;
  GtkWidget* canvas_ = nullptr;
  GtkWidget* status_ = nullptr;
  UINT16 pointer_x_ = 0;
  UINT16 pointer_y_ = 0;
  std::set<UINT16> keys_;
  std::set<unsigned> buttons_;

  const HANDLE wake_;
  std::mutex mutex_;
  std::condition_variable certificate_reply_;
  HANDLE abort_ = nullptr;
  bool stopping_ = false;
  bool connected_ = false;
  bool frame_pending_ = false;
  bool paint_pending_ = false;
  int certificate_answer_ = -1;
  bool certificate_host_mismatch_ = false;
  std::string certificate_;
  std::string error_;
  Frame frame_;
  std::vector<Input> pending_input_;
};

bool Session::Open(GtkApplication* app, const std::string& host, unsigned port,
                   std::string username, const char* password) {
  auto session = std::make_shared<Session>();
  if (!session->wake_) return false;
  static const DWORD layout = freerdp_keyboard_init(0);

  GtkWidget* window = gtk_application_window_new(app);
  session->window_ = window;
  gtk_window_set_title(GTK_WINDOW(window), ("RustDesk RDP — " + host).c_str());
  gtk_window_set_default_size(GTK_WINDOW(window), 1024, 640);
  if (GtkWindow* parent = gtk_application_get_active_window(app)) {
    if (parent != GTK_WINDOW(window)) {
      gtk_window_set_transient_for(GTK_WINDOW(window), parent);
      gtk_window_set_destroy_with_parent(GTK_WINDOW(window), TRUE);
    }
  }

  GtkWidget* overlay = gtk_overlay_new();
  gtk_container_add(GTK_CONTAINER(window), overlay);
  session->canvas_ = gtk_drawing_area_new();
  gtk_widget_set_can_focus(session->canvas_, TRUE);
  gtk_widget_add_events(session->canvas_,
                        GDK_POINTER_MOTION_MASK | GDK_BUTTON_PRESS_MASK |
                            GDK_BUTTON_RELEASE_MASK | GDK_SCROLL_MASK |
                            GDK_SMOOTH_SCROLL_MASK | GDK_KEY_PRESS_MASK |
                            GDK_KEY_RELEASE_MASK | GDK_FOCUS_CHANGE_MASK);
  gtk_container_add(GTK_CONTAINER(overlay), session->canvas_);
  session->status_ = gtk_label_new("Connecting…");
  gtk_widget_set_halign(session->status_, GTK_ALIGN_CENTER);
  gtk_widget_set_valign(session->status_, GTK_ALIGN_CENTER);
  gtk_label_set_line_wrap(GTK_LABEL(session->status_), TRUE);
  gtk_label_set_max_width_chars(GTK_LABEL(session->status_), 70);
  gtk_overlay_add_overlay(GTK_OVERLAY(overlay), session->status_);

  g_object_set_data_full(G_OBJECT(window), "rustdesk-rdp-session",
                         new std::shared_ptr<Session>(session),
                         [](gpointer data) {
                           delete static_cast<std::shared_ptr<Session>*>(data);
                         });
  auto* self = session.get();
  g_signal_connect(window, "destroy",
                   G_CALLBACK(+[](GtkWidget*, gpointer data) {
                     static_cast<Session*>(data)->Stop();
                   }),
                   self);
  g_signal_connect(
      session->canvas_, "draw",
      G_CALLBACK(+[](GtkWidget*, cairo_t* cr, gpointer data) -> gboolean {
        static_cast<Session*>(data)->Draw(cr);
        return TRUE;
      }),
      self);
  g_signal_connect(session->canvas_, "motion-notify-event",
                   G_CALLBACK(+[](GtkWidget*, GdkEventMotion* event,
                                  gpointer data) -> gboolean {
                     auto* session = static_cast<Session*>(data);
                     UINT16 x;
                     UINT16 y;
                     if (session->Point(event->x, event->y,
                                        !session->buttons_.empty(), x, y))
                       session->Queue({Input::Mouse, PTR_FLAGS_MOVE, x, y});
                     return TRUE;
                   }),
                   self);
  auto button =
      +[](GtkWidget* widget, GdkEventButton* event, gpointer data) -> gboolean {
    if (event->type == GDK_BUTTON_PRESS) gtk_widget_grab_focus(widget);
    static_cast<Session*>(data)->Button(*event);
    return TRUE;
  };
  g_signal_connect(session->canvas_, "button-press-event", G_CALLBACK(button),
                   self);
  g_signal_connect(session->canvas_, "button-release-event", G_CALLBACK(button),
                   self);
  auto key = +[](GtkWidget*, GdkEventKey* event, gpointer data) -> gboolean {
    static_cast<Session*>(data)->Key(*event);
    return TRUE;
  };
  g_signal_connect(session->canvas_, "key-press-event", G_CALLBACK(key), self);
  g_signal_connect(session->canvas_, "key-release-event", G_CALLBACK(key),
                   self);
  auto focus =
      +[](GtkWidget*, GdkEventFocus* event, gpointer data) -> gboolean {
    static_cast<Session*>(data)->Focus(event->in);
    return FALSE;
  };
  g_signal_connect(session->canvas_, "focus-in-event", G_CALLBACK(focus), self);
  g_signal_connect(session->canvas_, "focus-out-event", G_CALLBACK(focus),
                   self);
  g_signal_connect(session->canvas_, "scroll-event",
                   G_CALLBACK(+[](GtkWidget*, GdkEventScroll* event,
                                  gpointer data) -> gboolean {
                     static_cast<Session*>(data)->Scroll(*event);
                     return TRUE;
                   }),
                   self);
  gtk_widget_add_tick_callback(
      window,
      +[](GtkWidget*, GdkFrameClock*, gpointer data) -> gboolean {
        return static_cast<Session*>(data)->Tick();
      },
      self, nullptr);

  try {
    std::thread([session, host, port, username = std::move(username),
                 password = std::string(password)]() mutable {
      try {
        session->Run(host, port, std::move(username), password, layout);
      } catch (const std::exception& error) {
        session->Finish(error.what());
      }
    }).detach();
  } catch (const std::system_error&) {
    gtk_widget_destroy(window);
    return false;
  }
  gtk_widget_show_all(window);
  gtk_widget_grab_focus(session->canvas_);
  return true;
}

BOOL Session::Resize(rdpContext* context) {
  const auto width =
      freerdp_settings_get_uint32(context->settings, FreeRDP_DesktopWidth);
  const auto height =
      freerdp_settings_get_uint32(context->settings, FreeRDP_DesktopHeight);
  if (width == 0 || height == 0 || width > 8192 || height > 8192 ||
      !gdi_resize(context->gdi, width, height))
    return FALSE;
  From(context).paint_pending_ = true;
  return TRUE;
}

BOOL Session::PostConnect(freerdp* client) {
  const auto width =
      freerdp_settings_get_uint32(client->settings, FreeRDP_DesktopWidth);
  const auto height =
      freerdp_settings_get_uint32(client->settings, FreeRDP_DesktopHeight);
  if (width == 0 || height == 0 || width > 8192 || height > 8192) return FALSE;
#if G_BYTE_ORDER == G_LITTLE_ENDIAN
  const auto format = PIXEL_FORMAT_BGRX32;
#else
  const auto format = PIXEL_FORMAT_XRGB32;
#endif
  if (!gdi_init(client, format)) return FALSE;
  client->update->EndPaint = [](rdpContext* context) -> BOOL {
    From(context).paint_pending_ = true;
    return TRUE;
  };
  client->update->DesktopResize = Resize;
  From(client->context).paint_pending_ = true;
  return TRUE;
}

void Session::Run(const std::string& host, unsigned port, std::string username,
                  const std::string& password, DWORD layout) {
  const auto cleanup = [this](freerdp* client) {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      abort_ = nullptr;
    }
    if (client->context) {
      freerdp_disconnect(client);
      if (client->context->gdi) gdi_free(client);
      freerdp_context_free(client);
    }
    freerdp_free(client);
  };
  std::unique_ptr<freerdp, decltype(cleanup)> client(freerdp_new(), cleanup);
  if (!client) {
    Finish("Could not initialize RDP.");
    return;
  }
  client->ContextSize = sizeof(Context);
  client->PostConnect = PostConnect;
  client->VerifyCertificateEx =
      [](freerdp* instance, const char*, UINT16, const char*, const char*,
         const char*, const char* fingerprint, DWORD flags) -> DWORD {
    return From(instance->context)
        .Verify(fingerprint, flags & VERIFY_CERT_FLAG_MISMATCH);
  };
  client->VerifyChangedCertificateEx =
      [](freerdp*, const char*, UINT16, const char*, const char*, const char*,
         const char*, const char*, const char*, const char*,
         DWORD) -> DWORD { return 0; };
  if (!freerdp_context_new(client.get())) {
    Finish("Could not initialize the RDP connection.");
    return;
  }
  reinterpret_cast<Context*>(client->context)->session = this;

  std::string domain;
  const auto separator = username.find('\\');
  if (separator != std::string::npos) {
    domain = username.substr(0, separator);
    username.erase(0, separator + 1);
  }
  rdpSettings* settings = client->settings;
  if (!freerdp_settings_set_string(settings, FreeRDP_ServerHostname,
                                   host.c_str()) ||
      !freerdp_settings_set_uint32(settings, FreeRDP_ServerPort, port) ||
      !freerdp_settings_set_string(settings, FreeRDP_Username,
                                   username.c_str()) ||
      !freerdp_settings_set_string(settings, FreeRDP_Domain, domain.c_str()) ||
      !freerdp_settings_set_string(settings, FreeRDP_Password,
                                   password.c_str()) ||
      !freerdp_settings_set_uint32(settings, FreeRDP_DesktopWidth, 1280) ||
      !freerdp_settings_set_uint32(settings, FreeRDP_DesktopHeight, 720) ||
      !freerdp_settings_set_uint32(settings, FreeRDP_ColorDepth, 32) ||
      !freerdp_settings_set_uint32(settings, FreeRDP_KeyboardLayout, layout) ||
      !freerdp_settings_set_bool(settings, FreeRDP_NlaSecurity, TRUE) ||
      !freerdp_settings_set_bool(settings, FreeRDP_TlsSecurity, TRUE) ||
      !freerdp_settings_set_bool(settings, FreeRDP_RdpSecurity, FALSE)) {
    Finish("Could not configure the RDP connection.");
    return;
  }
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (stopping_) return;
    abort_ = client->context->abortEvent;
  }
  if (freerdp_connect(client.get())) {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      connected_ = !stopping_;
    }
    while (!freerdp_shall_disconnect(client.get())) {
      if (paint_pending_) {
        paint_pending_ = false;
        if (!PublishFrame(client->context->gdi)) {
          Finish("Could not display the remote desktop.");
          return;
        }
      }
      HANDLE handles[MAXIMUM_WAIT_OBJECTS] = {wake_};
      DWORD count = freerdp_get_event_handles(client->context, handles + 1,
                                              MAXIMUM_WAIT_OBJECTS - 1);
      if (count == 0 ||
          WaitForMultipleObjects(count + 1, handles, FALSE, INFINITE) ==
              WAIT_FAILED ||
          !ProcessInput(client->input) ||
          !freerdp_check_event_handles(client->context))
        break;
    }
  }
  const auto code = freerdp_get_last_error(client->context);
  const char* error = code ? freerdp_get_last_error_string(code) : nullptr;
  Finish(error ? error : "RDP connection closed.");
}

void Session::Stop() {
  std::lock_guard<std::mutex> lock(mutex_);
  stopping_ = true;
  certificate_reply_.notify_one();
  if (abort_) SetEvent(abort_);
  SetEvent(wake_);
}

void Session::Finish(const std::string& message) {
  std::lock_guard<std::mutex> lock(mutex_);
  connected_ = false;
  if (!stopping_ && error_.empty()) error_ = message;
}

void Session::Queue(Input input) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!connected_ || stopping_) return;
  if (input.kind == Input::Mouse && input.flags == PTR_FLAGS_MOVE &&
      !pending_input_.empty() && pending_input_.back().kind == Input::Mouse &&
      pending_input_.back().flags == PTR_FLAGS_MOVE) {
    pending_input_.back() = input;
  } else if (pending_input_.size() < 512) {
    pending_input_.push_back(input);
  } else {
    error_ = "RDP input could not be delivered.";
  }
  SetEvent(wake_);
}

bool Session::ProcessInput(rdpInput* input) {
  std::vector<Input> events;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (stopping_ || !error_.empty()) return false;
    events.swap(pending_input_);
    ResetEvent(wake_);
  }
  return std::all_of(events.begin(), events.end(),
                     [input](const Input& event) { return event.Send(input); });
}

DWORD Session::Verify(const char* fingerprint, bool host_mismatch) {
  if (!fingerprint || !*fingerprint) return 0;
  std::unique_lock<std::mutex> lock(mutex_);
  certificate_ = fingerprint;
  certificate_host_mismatch_ = host_mismatch;
  certificate_answer_ = -1;
  certificate_reply_.wait(
      lock, [this] { return stopping_ || certificate_answer_ >= 0; });
  return stopping_ ? 0 : certificate_answer_;
}

bool Session::PublishFrame(rdpGdi* gdi) {
  if (!gdi || !gdi->primary_buffer || gdi->width <= 0 || gdi->height <= 0 ||
      gdi->stride < static_cast<UINT32>(gdi->width) * 4)
    return false;
  std::lock_guard<std::mutex> lock(mutex_);
  frame_.width = gdi->width;
  frame_.height = gdi->height;
  frame_.stride = gdi->stride;
  frame_.data.assign(
      gdi->primary_buffer,
      gdi->primary_buffer + static_cast<size_t>(gdi->height) * gdi->stride);
  frame_pending_ = true;
  return true;
}

bool Session::Tick() {
  bool redraw;
  bool host_mismatch;
  std::string fingerprint, error;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    redraw = frame_pending_;
    frame_pending_ = false;
    fingerprint.swap(certificate_);
    host_mismatch = certificate_host_mismatch_;
    error = error_;
  }
  if (!error.empty()) {
    gtk_label_set_text(GTK_LABEL(status_), error.c_str());
    gtk_widget_show(status_);
    gtk_widget_queue_draw(canvas_);
    return false;
  }
  if (!fingerprint.empty()) {
    GtkWidget* dialog = gtk_message_dialog_new(
        GTK_WINDOW(window_),
        static_cast<GtkDialogFlags>(GTK_DIALOG_MODAL |
                                    GTK_DIALOG_DESTROY_WITH_PARENT),
        GTK_MESSAGE_WARNING, GTK_BUTTONS_NONE, "%s",
        "Verify the RDP server certificate");
    gtk_message_dialog_format_secondary_text(
        GTK_MESSAGE_DIALOG(dialog), "%s\n\n%s",
        host_mismatch
            ? "The certificate name does not match the address. Compare the "
              "fingerprint with the server before continuing."
            : "Compare this fingerprint with the server before continuing.",
        fingerprint.c_str());
    gtk_dialog_add_buttons(GTK_DIALOG(dialog), "_Cancel", GTK_RESPONSE_CANCEL,
                           "_Trust for this session", GTK_RESPONSE_ACCEPT,
                           nullptr);
    gtk_dialog_set_default_response(GTK_DIALOG(dialog), GTK_RESPONSE_CANCEL);
    g_signal_connect(
        dialog, "response",
        G_CALLBACK(+[](GtkDialog* dialog, gint response, gpointer data) {
          auto* session = static_cast<Session*>(data);
          {
            std::lock_guard<std::mutex> lock(session->mutex_);
            session->certificate_answer_ =
                response == GTK_RESPONSE_ACCEPT ? 2 : 0;
            session->certificate_reply_.notify_one();
          }
          gtk_widget_destroy(GTK_WIDGET(dialog));
        }),
        this);
    gtk_widget_show(dialog);
  }
  if (redraw) {
    if (gtk_widget_get_visible(status_)) {
      gtk_widget_hide(status_);
      if (gtk_widget_has_focus(canvas_)) Focus(true);
    }
    gtk_widget_queue_draw(canvas_);
  }
  return true;
}

Viewport Session::GetViewport() const {
  const auto width = gtk_widget_get_allocated_width(canvas_);
  const auto height = gtk_widget_get_allocated_height(canvas_);
  const auto scale = std::min(static_cast<double>(width) / frame_.width,
                              static_cast<double>(height) / frame_.height);
  return {scale, (width - frame_.width * scale) / 2,
          (height - frame_.height * scale) / 2};
}

void Session::Draw(cairo_t* cr) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (frame_.data.empty() || !error_.empty()) return;
  cairo_set_source_rgb(cr, 0, 0, 0);
  cairo_paint(cr);
  const auto view = GetViewport();
  if (view.scale <= 0) return;
  cairo_surface_t* surface = cairo_image_surface_create_for_data(
      frame_.data.data(), CAIRO_FORMAT_RGB24, frame_.width, frame_.height,
      frame_.stride);
  cairo_save(cr);
  cairo_translate(cr, view.x, view.y);
  cairo_scale(cr, view.scale, view.scale);
  cairo_set_source_surface(cr, surface, 0, 0);
  cairo_paint(cr);
  cairo_restore(cr);
  cairo_surface_destroy(surface);
}

bool Session::Point(double x, double y, bool clamp, UINT16& remote_x,
                    UINT16& remote_y) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (!connected_ || frame_.data.empty()) return false;
  const auto view = GetViewport();
  if (view.scale <= 0) return false;
  x = (x - view.x) / view.scale;
  y = (y - view.y) / view.scale;
  if (!clamp && (x < 0 || x >= frame_.width || y < 0 || y >= frame_.height))
    return false;
  remote_x = pointer_x_ =
      std::max(0.0, std::min(x, static_cast<double>(frame_.width - 1)));
  remote_y = pointer_y_ =
      std::max(0.0, std::min(y, static_cast<double>(frame_.height - 1)));
  return true;
}

Input MouseButton(unsigned button, bool down, UINT16 x, UINT16 y) {
  const UINT16 buttons[] = {0, PTR_FLAGS_BUTTON1, PTR_FLAGS_BUTTON3,
                            PTR_FLAGS_BUTTON2};
  if (button == 8 || button == 9)
    return {Input::ExtendedMouse,
            static_cast<UINT16>(
                (button == 8 ? PTR_XFLAGS_BUTTON1 : PTR_XFLAGS_BUTTON2) |
                (down ? PTR_XFLAGS_DOWN : 0)),
            x, y};
  return {Input::Mouse,
          static_cast<UINT16>(buttons[button] | (down ? PTR_FLAGS_DOWN : 0)), x,
          y};
}

void Session::Button(const GdkEventButton& event) {
  if (event.button == 0 ||
      (event.button > 3 && event.button != 8 && event.button != 9))
    return;
  const bool down = event.type == GDK_BUTTON_PRESS;
  if (!down && event.type != GDK_BUTTON_RELEASE) return;
  UINT16 x, y;
  if (down) {
    if (!Point(event.x, event.y, false, x, y)) return;
    buttons_.insert(event.button);
  } else {
    if (!buttons_.erase(event.button) || !Point(event.x, event.y, true, x, y))
      return;
  }
  Queue(MouseButton(event.button, down, x, y));
}

void Session::Key(const GdkEventKey& event) {
  const auto key =
      GetVirtualKeyCodeFromKeycode(event.hardware_keycode, KEYCODE_TYPE_EVDEV);
  const auto scan = GetVirtualScanCodeFromVirtualKeyCode(key, 4);
  if (!scan) return;
  const bool down = event.type == GDK_KEY_PRESS;
  if (down) {
    keys_.insert(scan);
  } else if (!keys_.erase(scan)) {
    return;
  }
  Queue({Input::Key, static_cast<UINT16>(down), static_cast<UINT16>(scan)});
}

void Session::Focus(bool focused) {
  if (focused) {
    GdkKeymap* keymap =
        gdk_keymap_get_for_display(gtk_widget_get_display(canvas_));
    const UINT16 locks =
        (gdk_keymap_get_caps_lock_state(keymap) ? KBD_SYNC_CAPS_LOCK : 0) |
        (gdk_keymap_get_num_lock_state(keymap) ? KBD_SYNC_NUM_LOCK : 0);
    Queue({Input::Sync, locks});
    return;
  }
  for (auto scan : keys_) Queue({Input::Key, 0, scan});
  for (auto button : buttons_)
    Queue(MouseButton(button, false, pointer_x_, pointer_y_));
  keys_.clear();
  buttons_.clear();
}

void Session::Scroll(const GdkEventScroll& event) {
  UINT16 x, y;
  if (!Point(event.x, event.y, false, x, y)) return;
  double dx = 0, dy = 0;
  switch (event.direction) {
    case GDK_SCROLL_UP:
      dy = -1;
      break;
    case GDK_SCROLL_DOWN:
      dy = 1;
      break;
    case GDK_SCROLL_LEFT:
      dx = -1;
      break;
    case GDK_SCROLL_RIGHT:
      dx = 1;
      break;
    case GDK_SCROLL_SMOOTH:
      dx = event.delta_x;
      dy = event.delta_y;
      break;
  }
  auto send = [this, x, y](UINT16 flags, double delta) {
    const int rotation =
        static_cast<int>(std::max(-255.0, std::min(delta * 120, 255.0)));
    if (rotation)
      Queue({Input::Mouse,
             static_cast<UINT16>(flags | (rotation & WheelRotationMask)), x,
             y});
  };
  send(PTR_FLAGS_WHEEL, -dy);
  send(PTR_FLAGS_HWHEEL, dx);
}

}  // namespace

gboolean rustdesk_rdp_open(GtkApplication* app, const char* host, unsigned port,
                           const char* username, const char* password) {
  return Session::Open(app, host, port, username, password);
}
