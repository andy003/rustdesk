import 'package:flutter/material.dart';
import 'package:get/get.dart';

import '../../common.dart';
import '../../common/widgets/login.dart';

enum _AccountAction { settings, logout }

class WorkspaceAccountButton extends StatelessWidget {
  const WorkspaceAccountButton({super.key, this.openSettings});

  final VoidCallback? openSettings;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(10),
      side: BorderSide(color: colors.primary.withOpacity(0.28)),
    );
    final user = gFFI.userModel;
    final avatar = CircleAvatar(
      radius: 15,
      backgroundColor: colors.primary.withOpacity(0.16),
      foregroundColor: colors.primary,
      child: const Icon(Icons.person_outline_rounded, size: 18),
    );

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 9),
      child: Obx(() {
        final signedIn = user.isLogin;
        final row = Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
          child: Row(
            children: [
              avatar,
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  signedIn ? user.displayNameOrUserName : translate('Sign in'),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.labelLarge?.copyWith(
                    color: signedIn ? colors.onSurface : colors.primary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              Icon(
                signedIn
                    ? Icons.keyboard_arrow_down_rounded
                    : Icons.chevron_right_rounded,
                size: 18,
                color: signedIn ? colors.onSurfaceVariant : colors.primary,
              ),
            ],
          ),
        );
        return Material(
          color: colors.primary.withOpacity(0.085),
          shape: shape,
          clipBehavior: Clip.antiAlias,
          child: signedIn
              ? PopupMenuButton<_AccountAction>(
                  tooltip: user.accountLabelWithHandle,
                  position: PopupMenuPosition.under,
                  onSelected: (action) {
                    switch (action) {
                      case _AccountAction.settings:
                        openSettings?.call();
                        break;
                      case _AccountAction.logout:
                        logOutConfirmDialog();
                        break;
                    }
                  },
                  itemBuilder: (_) => [
                    if (openSettings != null)
                      PopupMenuItem(
                        value: _AccountAction.settings,
                        child: Text(translate('Account')),
                      ),
                    PopupMenuItem(
                      value: _AccountAction.logout,
                      child: Text(translate('Logout')),
                    ),
                  ],
                  child: row,
                )
              : InkWell(onTap: loginDialog, child: row),
        );
      }),
    );
  }
}
