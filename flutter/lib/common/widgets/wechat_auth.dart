import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../common.dart';
import '../../models/platform_model.dart';
import '../../utils/http_service.dart' as http;
import '../hbbs/hbbs.dart';

class WechatAuthButton extends StatefulWidget {
  const WechatAuthButton.signIn(
      {super.key, required this.onSignedIn, this.enabled = true})
      : link = false;

  const WechatAuthButton.link({super.key})
      : link = true,
        enabled = true,
        onSignedIn = null;

  final bool link;
  final bool enabled;
  final Future<void> Function(String, Map<String, dynamic>)? onSignedIn;

  @override
  State<WechatAuthButton> createState() => _WechatAuthButtonState();
}

class _WechatAuthButtonState extends State<WechatAuthButton> {
  late final Future<String?> _server = _availableServer();
  bool _busy = false;

  Future<String?> _availableServer() async {
    if (!isDesktop || http.managedAccountServer.isEmpty) return null;
    try {
      final server = await bind.mainGetApiServer();
      if (server != http.managedAccountServer) return null;
      final response = await http.get(Uri.parse('$server/api/wechat/status'));
      if (response.statusCode == 200 &&
          jsonDecode(decode_http_response(response))['enabled'] == true) {
        return server;
      }
    } catch (_) {
      return null;
    }
    return null;
  }

  Future<void> _authorize(String server) async {
    setState(() => _busy = true);
    try {
      final result = await gFFI.dialogManager.show<Map<String, dynamic>>(
        (_, close, __) => CustomAlertDialog(
          title: Text(
              translate(widget.link ? 'Link WeChat' : 'Sign in with WeChat')),
          contentBoxConstraints:
              const BoxConstraints(minWidth: 300, maxWidth: 450),
          content: _WechatAuthContent(
              server: server, link: widget.link, finish: close),
          onCancel: close,
        ),
      );
      if (result == null || !mounted) return;
      if (widget.link) {
        showToast(translate('WeChat linked'));
      } else {
        await widget.onSignedIn!(server, result);
      }
    } catch (_) {
      if (mounted) showToast(translate('WeChat authorization failed'));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<String?>(
        future: _server,
        builder: (_, snapshot) {
          final server = snapshot.data;
          if (server == null) return const SizedBox.shrink();
          return Padding(
            padding: const EdgeInsets.only(top: 12),
            child: OutlinedButton.icon(
              onPressed:
                  _busy || !widget.enabled ? null : () => _authorize(server),
              icon: const Icon(Icons.qr_code_scanner, size: 18),
              label: Text(translate(
                  widget.link ? 'Link WeChat' : 'Sign in with WeChat')),
            ),
          );
        },
      );
}

class _WechatAuthContent extends StatefulWidget {
  const _WechatAuthContent({
    required this.server,
    required this.link,
    required this.finish,
  });

  final String server;
  final bool link;
  final void Function([dynamic]) finish;

  @override
  State<_WechatAuthContent> createState() => _WechatAuthContentState();
}

class _WechatAuthContentState extends State<_WechatAuthContent> {
  final _password = TextEditingController();
  Uri? _authorizationUrl;
  String? _error;
  bool _browserFailed = false;
  late bool _started = !widget.link;

  @override
  void initState() {
    super.initState();
    if (_started) unawaited(_authorize());
  }

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> _post(String operation, String bearer,
      [Map<String, String>? fields]) async {
    final response = await http.post(
      Uri.parse('${widget.server}/api/wechat/$operation'),
      headers: {
        'Content-Type': 'application/json',
        if (bearer.isNotEmpty) 'Authorization': 'Bearer $bearer',
      },
      body: jsonEncode(fields ?? <String, String>{}),
    );
    final data =
        jsonDecode(decode_http_response(response)) as Map<String, dynamic>;
    if (response.statusCode != 200) {
      throw RequestException(
        response.statusCode,
        data['error'] as String? ?? 'WeChat authorization failed',
      );
    }
    return data;
  }

  void _startLink() {
    final password = _password.text;
    if (_started || password.isEmpty) return;
    _password.clear();
    setState(() {
      _started = true;
      _error = null;
    });
    unawaited(_authorize(password));
  }

  Future<void> _authorize([String? password]) async {
    try {
      final token =
          widget.link ? bind.mainGetLocalOption(key: 'access_token') : '';
      final start = await _post(widget.link ? 'link' : 'start', token,
          password == null ? null : {'password': password});
      if (!mounted) return;
      final url = Uri.parse(start['url'] as String);
      if (url.scheme != 'https' ||
          url.host != 'open.weixin.qq.com' ||
          url.port != 443 ||
          url.userInfo.isNotEmpty ||
          url.path != '/connect/qrconnect') {
        throw const FormatException('Invalid WeChat authorization URL');
      }
      final verifier = start['verifier'] as String;
      final expiry = Stopwatch()..start();
      final duration = Duration(seconds: start['expires_in'] as int);
      setState(() => _authorizationUrl = url);
      await _openBrowser();
      while (mounted && expiry.elapsed < duration) {
        await Future<void>.delayed(const Duration(seconds: 2));
        if (!mounted) return;
        final result = await _post('poll', verifier);
        if (!mounted) return;
        if (result['status'] == 'pending') continue;
        if (widget.link
            ? result['status'] == 'linked'
            : result['type'] == HttpType.kAuthResTypeToken) {
          widget.finish(result);
          return;
        }
        throw const FormatException('Invalid WeChat authorization result');
      }
      if (mounted) setState(() => _error = 'WeChat request expired');
    } on RequestException catch (error) {
      if (mounted) {
        setState(() {
          _error = error.cause;
          if (widget.link &&
              _authorizationUrl == null &&
              error.statusCode == 401) {
            _started = false;
          }
        });
      }
    } catch (_) {
      if (mounted) setState(() => _error = 'WeChat authorization failed');
    }
  }

  Future<void> _openBrowser() async {
    final url = _authorizationUrl;
    if (url == null) return;
    var opened = false;
    try {
      opened = await launchUrl(url, mode: LaunchMode.externalApplication);
    } catch (_) {
      // Keep the button available to retry opening the authorization URL.
    }
    if (mounted) setState(() => _browserFailed = !opened);
  }

  @override
  Widget build(BuildContext context) => Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (!_started)
            TextField(
              controller: _password,
              obscureText: true,
              autofocus: true,
              onSubmitted: (_) => _startLink(),
              decoration: InputDecoration(
                labelText: translate('Password'),
                errorText: _error == null ? null : translate(_error!),
              ),
            )
          else if (_error != null)
            Text(translate(_error!))
          else if (_authorizationUrl == null)
            const LinearProgressIndicator()
          else ...[
            Text(translate('Scan with WeChat in your browser')),
            if (!_browserFailed) const LinearProgressIndicator(),
            TextButton(
              onPressed: _openBrowser,
              child: Text(translate('Open in browser')),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                  onPressed: widget.finish, child: Text(translate('Cancel'))),
              if (!_started)
                FilledButton(
                    onPressed: _startLink, child: Text(translate('Continue'))),
            ],
          ),
        ],
      );
}
