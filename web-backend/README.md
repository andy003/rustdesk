# RustDesk 账号与设备管理

管理员在 Web 后台创建账号和管理设备归属。用户在每台 RustDesk 客户端登录同一账号后，本机自动加入账号设备列表。桌面客户端从左侧「设备」查看同账号的其他设备，点击「连接」后输入被控设备的独立密码。

从受管设备列表发起的新连接会要求手动输入设备密码。直接输入 RustDesk ID 和设备密码的远程协助也可继续使用。设备密码由被控端保存和校验，账号后端只管理账号、登录令牌和设备归属。

## 本地运行

需要 Python 3.10 或更高版本。进入 `web-backend/` 后执行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export RUSTDESK_WEB_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export RUSTDESK_WEB_DEVELOPMENT=1
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

1. 打开 [本地后台](http://127.0.0.1:8000/admin/)，创建普通用户。
2. 让账号后端以只读方式访问同一套开源 RustDesk ID 服务的 `db_v2.sqlite3`，以及 SQLite 使用的 WAL 文件。在启动账号后端前，将 `RUSTDESK_WEB_HBBS_DATABASE` 设为该数据库的绝对路径。账号后端使用 ID 服务已登记的设备公钥验证本机，已有的设备归属由管理员调整。
3. 在每台被控设备的 RustDesk 安全设置中设置固定密码，将批准模式设为「密码」，验证方式设为「仅使用固定密码」。主控和被控客户端使用同一套自建 RustDesk ID 和中继服务及相应的公钥。
4. 使用从本仓库构建的 Flutter 原生客户端。进入「设置 → 网络」，把 `API Server` 设置为账号后端的地址。本机测试可用 `http://127.0.0.1:8000`，异机使用部署后的 HTTPS 地址。`ID Server`、`Relay Server` 和 `Key` 使用现有 RustDesk 服务配置。
5. 在各台 RustDesk 客户端的「账号」中登录同一账号。桌面端打开左侧「设备」，选择一台设备连接，并输入它的固定密码。连接 ID 服务前若绑定未成功，等客户端显示就绪后在设备页刷新。未配置 ID 数据库时，由管理员在后台手动分配设备。

运行测试：`python manage.py test`。

## 部署

公网环境使用 `deploy/` 中的 systemd 和 Nginx 配置。Gunicorn 仅监听 `127.0.0.1:18761`。Nginx 在 HTTPS 虚拟主机加载 `nginx-locations.conf`，在 `http` 块加载 `nginx-http.conf`，并将两个引用的片段安装到 `/etc/nginx/snippets/`。管理地址为 [RustDesk 管理后台](https://www.ccrosrobot.com/rustdesk/admin/)。

部署时关闭 `RUSTDESK_WEB_DEVELOPMENT`。在仅 root 可读的环境文件中配置随机持久的 `RUSTDESK_WEB_SECRET_KEY`、`RUSTDESK_WEB_HOSTS`、`RUSTDESK_WEB_PATH=/rustdesk` 和持久的 `RUSTDESK_WEB_DATABASE`。反向代理须覆盖 `X-Forwarded-Proto`，并设 `RUSTDESK_WEB_TRUST_PROXY=1`。执行 `migrate`、`collectstatic --noinput` 和 `check --deploy` 后启动服务。生产管理员需要在 Django shell 为其创建一个已确认的 `django_otp.plugins.otp_totp.models.TOTPDevice`，并使用私密渠道交付初始密码和 TOTP 密钥。普通客户端账号与后台管理员账号分开使用。

`RUSTDESK_WEB_HBBS_SOURCE` 指定 ID 服务的在线数据库。同步服务只向 `RUSTDESK_WEB_HBBS_DATABASE` 发布已注册设备的 ID 和公钥，后台服务由非特权账号运行。指定 `RUSTDESK_WEB_ID_SERVER`、`RUSTDESK_WEB_RELAY_SERVER` 和 `RUSTDESK_WEB_SERVER_PUBLIC_KEY`（服务器的 `id_ed25519.pub`）后，账号 API 会在验证成功后返回网络配置。编译原生 Rust 客户端时设置 `RUSTDESK_ACCOUNT_BOOTSTRAP_URL=https://www.ccrosrobot.com/rustdesk`。该构建使用预设 HTTPS 地址登录，然后自动配置 ID 服务器、中继和公钥。客户端仍在连接时校验被控端的独立密码。

客户端令牌有效期为七天，退出登录、修改账号密码或停用账号后会失效。设备归属可在后台管理，远控及其独立密码校验由现有 RustDesk 服务处理。

## 微信扫码登录

在[微信开放平台](https://open.weixin.qq.com/)创建并提交「网站应用」审核，开通微信登录。授权回调域填写 `www.ccrosrobot.com`。审核完成后，通过服务器上的 root 私有环境文件配置 `RUSTDESK_WEB_WECHAT_APP_ID`、`RUSTDESK_WEB_WECHAT_APP_SECRET` 和 `RUSTDESK_WEB_WECHAT_CALLBACK_URL=https://www.ccrosrobot.com/rustdesk/api/wechat/callback`。AppSecret 只存放在服务器端。

部署本版本时运行数据库迁移，并更新 `deploy/` 下的 Nginx 配置，使扫码申请限速且回调查询参数不进入访问日志。环境变量齐全时，客户端登录窗口会显示「微信扫码登录」。

已有账号先在客户端用普通密码登录，进入「设置 → 账号 → 绑定微信」，再次验证账号密码，再通过系统浏览器打开的微信官方页面扫码。绑定后，其他客户端可从登录窗口走同一扫码流程，授权结果会返回客户端。首次使用需由管理员创建普通账号。后台可删除微信绑定，重新绑定时由用户再次输入账号密码。
