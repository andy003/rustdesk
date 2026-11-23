import 'package:flutter/material.dart';
import 'package:flutter_hbb/common.dart';
import 'package:flutter_hbb/common/formatter/id_formatter.dart';
import 'package:flutter_hbb/common/widgets/login.dart';
import 'package:flutter_hbb/common/widgets/peer_card.dart';
import 'package:flutter_hbb/models/peer_model.dart';
import 'package:flutter_hbb/models/peer_tab_model.dart';
import 'package:get/get.dart';

class AccountDevicesPage extends StatefulWidget {
  const AccountDevicesPage({super.key});

  @override
  State<AccountDevicesPage> createState() => _AccountDevicesPageState();
}

class _AccountDevicesPageState extends State<AccountDevicesPage> {
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final account = gFFI.userModel;
    final group = gFFI.groupModel;
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return ColoredBox(
      color: Color.alphaBlend(
          colors.primary.withOpacity(0.025), theme.scaffoldBackgroundColor),
      child: Obx(() {
        final signedIn = account.isLogin;
        final loading = group.groupLoading.value;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ColoredBox(
              color: theme.scaffoldBackgroundColor,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(28, 22, 28, 18),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(translate('Devices'),
                              style: theme.textTheme.headlineSmall
                                  ?.copyWith(fontWeight: FontWeight.w700)),
                        ),
                        if (signedIn)
                          IconButton.outlined(
                            tooltip: translate('Refresh devices'),
                            icon: const Icon(Icons.refresh_rounded, size: 19),
                            onPressed:
                                loading ? null : account.refreshCurrentUser,
                          ),
                      ],
                    ),
                    if (signedIn) ...[
                      const SizedBox(height: 4),
                      Text(account.accountLabelWithHandle,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.bodySmall
                              ?.copyWith(color: colors.onSurfaceVariant)),
                      const SizedBox(height: 18),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: _searchField(context),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const Divider(height: 1),
            if (signedIn && account.deviceBindingError.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(28, 14, 28, 0),
                child: Text(translate(account.deviceBindingError.value),
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: colors.error)),
              ),
            Expanded(child: _body(context, signedIn, loading)),
          ],
        );
      }),
    );
  }

  Widget _searchField(BuildContext context) {
    final theme = Theme.of(context);
    final radius = BorderRadius.circular(10);
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 420),
      child: TextField(
        controller: _search,
        onChanged: (_) => setState(() {}),
        decoration: InputDecoration(
          isDense: true,
          hintText: translate('Search devices'),
          prefixIcon: const Icon(Icons.search_rounded, size: 20),
          suffixIcon: _search.text.isEmpty
              ? null
              : IconButton(
                  tooltip: translate('Clear'),
                  icon: const Icon(Icons.close_rounded, size: 18),
                  onPressed: () => setState(_search.clear),
                ),
          filled: true,
          fillColor: theme.colorScheme.primary.withOpacity(0.035),
          enabledBorder: OutlineInputBorder(
            borderRadius: radius,
            borderSide: BorderSide(color: theme.dividerColor),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: radius,
            borderSide: BorderSide(color: theme.colorScheme.primary),
          ),
        ),
      ),
    );
  }

  Widget _body(BuildContext context, bool signedIn, bool loading) {
    final account = gFFI.userModel;
    final group = gFFI.groupModel;
    if (!signedIn) {
      return _emptyPanel(
        context,
        Icons.devices_rounded,
        'Sign in to see your devices',
        action: FilledButton(
          onPressed: loginDialog,
          child: Text(translate('Login')),
        ),
      );
    }
    if (account.networkError.isNotEmpty) return netWorkErrorWidget();
    if (group.groupLoadError.isNotEmpty) {
      return Center(child: Text(group.groupLoadError.value));
    }
    final myId = gFFI.serverModel.serverId.text.replaceAll(' ', '');
    final devices = group.peers
        .where((peer) =>
            peer.loginName == account.userName.value && peer.id != myId)
        .toList(growable: false);
    if (devices.isEmpty && loading) {
      return const Center(child: CircularProgressIndicator());
    }
    final query = _search.text.trim().toLowerCase();
    final normalizedId = query.replaceAll(' ', '');
    final matches = devices.where((peer) =>
        peer.hostname.toLowerCase().contains(query) ||
        peer.id.toLowerCase().contains(normalizedId));
    final rows = matches.toList(growable: false);
    if (rows.isEmpty) {
      return _emptyPanel(
        context,
        devices.isEmpty ? Icons.devices_rounded : Icons.search_off_rounded,
        devices.isEmpty
            ? 'No other devices in this account'
            : 'No devices found',
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.fromLTRB(28, 18, 28, 24),
      itemCount: rows.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (context, index) => _deviceRow(context, rows[index]),
    );
  }

  Widget _deviceRow(BuildContext context, Peer device) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return Material(
      color: theme.scaffoldBackgroundColor,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: theme.dividerColor),
      ),
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
        minLeadingWidth: 42,
        leading: DecoratedBox(
          decoration: BoxDecoration(
            color: colors.primary.withOpacity(0.09),
            borderRadius: BorderRadius.circular(10),
          ),
          child: SizedBox.square(
            dimension: 42,
            child: Center(
              child: device.platform.isEmpty
                  ? Icon(Icons.desktop_windows_outlined,
                      size: 22, color: colors.primary)
                  : ColorFiltered(
                      colorFilter:
                          ColorFilter.mode(colors.primary, BlendMode.srcIn),
                      child: getPlatformImage(device.platform, size: 22),
                    ),
            ),
          ),
        ),
        title: Text(device.hostname.isEmpty ? device.id : device.hostname,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.titleSmall
                ?.copyWith(fontWeight: FontWeight.w600)),
        subtitle: Text(formatID(device.id),
            style: theme.textTheme.bodySmall?.copyWith(
                color: colors.onSurfaceVariant, letterSpacing: 0.35)),
        trailing: OutlinedButton.icon(
          onPressed: () =>
              connectInPeerTab(context, device, PeerTabIndex.group),
          icon: const Icon(Icons.arrow_outward_rounded, size: 15),
          label: Text(translate('Connect')),
        ),
      ),
    );
  }

  Widget _emptyPanel(BuildContext context, IconData icon, String title,
      {Widget? action}) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircleAvatar(
              radius: 28,
              backgroundColor: theme.colorScheme.primary.withOpacity(0.09),
              child: Icon(icon, size: 25, color: theme.colorScheme.primary),
            ),
            const SizedBox(height: 14),
            Text(translate(title),
                textAlign: TextAlign.center, style: theme.textTheme.titleSmall),
            if (action != null) ...[const SizedBox(height: 14), action],
          ],
        ),
      ),
    );
  }
}
