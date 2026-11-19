import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_hbb/common.dart';
import 'package:flutter_hbb/utils/platform_channel.dart';

Future<void> showRdpConnectionDialog(BuildContext context) =>
    showDialog<void>(context: context, builder: (_) => const _RdpDialog());

class _RdpDialog extends StatefulWidget {
  const _RdpDialog();

  @override
  State<_RdpDialog> createState() => _RdpDialogState();
}

class _RdpDialogState extends State<_RdpDialog> {
  static final _hostname = RegExp(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$');
  final _form = GlobalKey<FormState>();
  final _host = TextEditingController();
  final _port = TextEditingController(text: '3389');
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _connecting = false;
  String? _error;

  @override
  void dispose() {
    _host.dispose();
    _port.dispose();
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _connect() async {
    if (_connecting || !_form.currentState!.validate()) return;
    setState(() {
      _connecting = true;
      _error = null;
    });
    try {
      await RdPlatformChannel.instance.connectRdp(
        host: _address(_host.text),
        port: int.parse(_port.text.trim()),
        username: _username.text.trim(),
        password: _password.text,
      );
      if (mounted) Navigator.of(context).pop();
    } on PlatformException catch (error) {
      if (!mounted) return;
      setState(() {
        _connecting = false;
        _error = error.message ?? translate('Error');
      });
    } on MissingPluginException {
      if (!mounted) return;
      setState(() {
        _connecting = false;
        _error = translate('Unsupported');
      });
    }
  }

  static String _address(String value) {
    final host = value.trim();
    if (host.startsWith('[') && host.endsWith(']')) {
      return host.substring(1, host.length - 1);
    }
    return host;
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('RDP'),
      scrollable: true,
      content: SizedBox(
        width: 340,
        child: Form(
          key: _form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _host,
                autofocus: true,
                autocorrect: false,
                decoration: InputDecoration(
                  labelText: translate('Remote Host'),
                  hintText: '192.168.1.10',
                ),
                validator: (value) {
                  final host = _address(value ?? '');
                  return _hostname.hasMatch(host) ||
                          InternetAddress.tryParse(host) != null
                      ? null
                      : translate('Invalid format');
                },
              ).workaroundFreezeLinuxMint(),
              TextFormField(
                controller: _port,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: InputDecoration(labelText: translate('Port')),
                validator: (value) {
                  final port = int.tryParse(value ?? '');
                  return port != null && port >= 1 && port <= 65535
                      ? null
                      : translate('Invalid port');
                },
              ).workaroundFreezeLinuxMint(),
              TextFormField(
                controller: _username,
                autocorrect: false,
                decoration: InputDecoration(labelText: translate('Username')),
                validator: (value) => value == null || value.trim().isEmpty
                    ? translate('Empty')
                    : null,
              ).workaroundFreezeLinuxMint(),
              TextFormField(
                controller: _password,
                obscureText: true,
                autocorrect: false,
                enableSuggestions: false,
                decoration: InputDecoration(labelText: translate('Password')),
                onFieldSubmitted: (_) => _connect(),
              ).workaroundFreezeLinuxMint(),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(_error!,
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error)),
                ),
            ],
          ),
        ),
      ),
      actions: [
        dialogButton('Cancel',
            onPressed: () => Navigator.of(context).pop(), isOutline: true),
        dialogButton('Connect', onPressed: _connecting ? null : _connect),
      ],
    );
  }
}
