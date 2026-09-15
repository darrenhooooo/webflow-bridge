/* Webflow Bridge popup — self-contained i18n (Chrome / Edge version).
 *
 * 16 languages, auto-detected from navigator.language (browser.i18n.
 * getUILanguage is used as a fallback where present). Matching: exact
 * region match wins (zh-HK -> Traditional), then a parent-language /
 * region mapping (zh without region -> Simplified, pt-BR/pt-PT -> pt,
 * en-US -> en, in -> id for legacy Indonesian), anything unknown ->
 * English.
 *
 * Arabic switches the document to dir="rtl" (see [dir="rtl"] rules in
 * popup.css). No external resources; no chrome.i18n _locales needed.
 *
 * Usage:  WBF_I18N.t('key'[, {placeholder: value}])
 *         Static markup: data-i18n="key" / data-i18n-title / data-i18n-placeholder
 *
 * Technical tokens (daemon, token, Firefox, BiDi, session, context, HTTP,
 * JS, URLs and paths) stay as-is in every language.
 */
(function () {
  'use strict';

  var MESSAGES = {

'en': {
  checking: 'Checking…',
  inactive: 'Inactive',
  reason_daemon_down: 'The daemon is not running',
  reason_daemon_busy: 'The daemon is already in use by another browser',
  active: 'Active',
  disconnected: 'Disconnected',
  disconnect: 'Disconnect',
  reconnect: 'Reconnect',
  wizard_title: 'Activation checklist',
  copy: 'Copy',
  copied: 'Copied ✓',
  copy_failed: 'Copy failed',
  unknown_error: 'unknown error',
  no_bg_response: 'no response from background',
  row_daemon: 'Daemon running',
  row_ext: 'Extension ready',
  row_page: 'Active tab debug-able',
  test_ok: 'Webflow Bridge is ready — the extension is running in {browser}.\nNext step: send a POST from your script or AI agent to http://127.0.0.1:10086/command to drive this tab (protocol: see docs/HTTP_API.md in the repo)',
  note_ext_down: 'Can’t check while the extension is down — reload it above.',
  daemon_lead: 'Start the daemon — pick either way:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge on GitHub',
  ext_fix_1: 'Open <b>{browser}</b>’s extensions page and make sure <b>Developer mode</b> is on.',
  ext_fix_2: 'Find <b>Webflow Bridge</b> and click its <b>Reload</b> button.',
  page_fix_switch: 'Switch the browser to a normal webpage tab — any http:// or https:// site.',
  page_fix_restricted: 'chrome:// pages, the Chrome Web Store and new-tab pages can’t be driven.',
  page_fix_restricted_edge: 'edge:// pages, the Edge Add-ons store and new-tab pages can’t be driven.',
  page_fix_devtools: 'Another debugger — usually DevTools (F12) — is attached to the active tab. Close it — the status above updates automatically.',
  page_fix_generic: 'The active tab can’t be driven right now. Switch to a normal http(s) page; if it keeps failing, close DevTools (F12) on the tab, then reload the extension using the command below and try again.'
},

'zh-CN': {
  checking: '检测中…',
  inactive: '未激活',
  reason_daemon_down: 'daemon 没运行',
  reason_daemon_busy: 'daemon 已被另一个浏览器占用',
  active: '已激活',
  disconnected: '已断开',
  disconnect: '断开连接',
  reconnect: '重新连接',
  wizard_title: '激活清单',
  copy: '复制',
  copied: '已复制 ✓',
  copy_failed: '复制失败',
  unknown_error: '未知错误',
  no_bg_response: '后台无响应',
  row_daemon: 'Daemon 运行中',
  row_ext: '扩展已就绪',
  row_page: '当前标签页可调试',
  test_ok: 'Webflow Bridge 已就绪 — 扩展正运行在 {browser}。\n下一步：从你的脚本或 AI agent 向 http://127.0.0.1:10086/command 发送 POST，即可驱动此标签页（协议见仓库 docs/HTTP_API.md）',
  note_ext_down: '扩展不可用时无法检查 — 请按上方步骤重新加载扩展。',
  daemon_lead: '启动本地 daemon — 任选一种方式：',
  cmd_python: 'Python：',
  cmd_uv: 'uv：',
  project_link: '在 GitHub 查看 Webflow Bridge',
  ext_fix_1: '打开 <b>{browser}</b> 的扩展管理页，确认已开启<b>开发者模式</b>。',
  ext_fix_2: '找到 <b>Webflow Bridge</b>，点击其<b>重新加载</b>按钮。',
  page_fix_switch: '将浏览器切换到普通网页标签页 — 任意 http:// 或 https:// 网站。',
  page_fix_restricted: 'chrome:// 页面、Chrome 应用商店和新标签页无法驱动。',
  page_fix_restricted_edge: 'edge:// 页面、Edge 加载项商店和新标签页无法驱动。',
  page_fix_devtools: '当前标签页已被另一个调试器 — 通常是 DevTools（F12）— 附加。关闭它，上方状态会自动更新。',
  page_fix_generic: '当前标签页暂时无法驱动。请切换到普通 http(s) 页面；若仍失败，关闭该标签页上的 DevTools（F12），然后用下方命令重新加载扩展再试。'
},

'zh-TW': {
  checking: '檢查中…',
  inactive: '未啟用',
  reason_daemon_down: 'daemon 未執行',
  reason_daemon_busy: 'daemon 已被另一個瀏覽器占用',
  active: '已啟用',
  disconnected: '已中斷',
  disconnect: '中斷連線',
  reconnect: '重新連線',
  wizard_title: '啟用清單',
  copy: '複製',
  copied: '已複製 ✓',
  copy_failed: '複製失敗',
  unknown_error: '未知錯誤',
  no_bg_response: '背景無回應',
  row_daemon: 'Daemon 執行中',
  row_ext: '擴充功能已就緒',
  row_page: '目前分頁可除錯',
  test_ok: 'Webflow Bridge 已就緒 — 擴充功能正執行於 {browser}。\n下一步：從你的腳本或 AI agent 向 http://127.0.0.1:10086/command 傳送 POST，即可驅動此分頁（協定見儲存庫 docs/HTTP_API.md）',
  note_ext_down: '擴充功能無法使用時無法檢查 — 請依上方步驟重新載入擴充功能。',
  daemon_lead: '啟動本機 daemon — 任選一種方式：',
  cmd_python: 'Python：',
  cmd_uv: 'uv：',
  project_link: '在 GitHub 查看 Webflow Bridge',
  ext_fix_1: '開啟 <b>{browser}</b> 的擴充功能管理頁，確認已開啟<b>開發人員模式</b>。',
  ext_fix_2: '找到 <b>Webflow Bridge</b>，點擊其<b>重新載入</b>按鈕。',
  page_fix_switch: '將瀏覽器切換到一般網頁分頁 — 任意 http:// 或 https:// 網站。',
  page_fix_restricted: 'chrome:// 頁面、Chrome 線上應用程式商店與新分頁無法驅動。',
  page_fix_restricted_edge: 'edge:// 頁面、Edge 附加元件商店與新分頁無法驅動。',
  page_fix_devtools: '目前分頁已被另一個偵錯工具 — 通常是 DevTools（F12）— 附加。關閉它，上方狀態會自動更新。',
  page_fix_generic: '目前分頁暫時無法驅動。請切換到一般 http(s) 頁面；若仍失敗，關閉該分頁上的 DevTools（F12），然後用下方命令重新載入擴充功能再試。'
},

'ja': {
  checking: '確認中…',
  inactive: '未アクティブ',
  reason_daemon_down: 'daemon が起動していません',
  reason_daemon_busy: 'daemon は別のブラウザーが使用中です',
  active: 'アクティブ',
  disconnected: '切断済み',
  disconnect: '切断',
  reconnect: '再接続',
  wizard_title: 'アクティブ化チェックリスト',
  copy: 'コピー',
  copied: 'コピーしました ✓',
  copy_failed: 'コピーに失敗しました',
  unknown_error: '不明なエラー',
  no_bg_response: 'バックグラウンドからの応答がありません',
  row_daemon: 'daemon 実行中',
  row_ext: '拡張機能の準備完了',
  row_page: 'アクティブなタブはデバッグ可能',
  test_ok: 'Webflow Bridge は準備完了です — 拡張機能は {browser} で動作しています。\n次のステップ：スクリプトまたは AI エージェントから http://127.0.0.1:10086/command へ POST を送信すると、このタブを操作できます（プロトコルはリポジトリの docs/HTTP_API.md を参照）',
  note_ext_down: '拡張機能が停止中は確認できません — 上記の手順で拡張機能を再読み込みしてください。',
  daemon_lead: 'ローカル daemon を起動 — どちらかの方法で：',
  cmd_python: 'Python：',
  cmd_uv: 'uv：',
  project_link: 'GitHub で Webflow Bridge を見る',
  ext_fix_1: '<b>{browser}</b> の拡張機能の管理ページを開き、<b>デベロッパー モード</b>をオンにしてください。',
  ext_fix_2: '<b>Webflow Bridge</b> を探して<b>再読み込み</b>ボタンをクリックしてください。',
  page_fix_switch: 'ブラウザを通常のウェブページのタブに切り替えてください — http:// や https:// のサイト。',
  page_fix_restricted: 'chrome:// ページ、Chrome ウェブストア、新規タブページは操作できません。',
  page_fix_restricted_edge: 'edge:// ページ、Edge アドオンストア、新規タブページは操作できません。',
  page_fix_devtools: '別のデバッガー（通常は DevTools（F12））がアクティブなタブにアタッチされています。閉じると、上のステータスは自動的に更新されます。',
  page_fix_generic: '現在アクティブなタブを操作できません。通常の http(s) ページに切り替えてください。それでも失敗する場合は、タブの DevTools（F12）を閉じ、下のコマンドで拡張機能を再読み込みしてもう一度お試しください。'
},

'ko': {
  checking: '확인 중…',
  inactive: '비활성',
  reason_daemon_down: 'daemon이 실행되고 있지 않습니다',
  reason_daemon_busy: 'daemon은 다른 브라우저에서 사용 중입니다',
  active: '활성',
  disconnected: '연결 끊김',
  disconnect: '연결 끊기',
  reconnect: '다시 연결',
  wizard_title: '활성화 체크리스트',
  copy: '복사',
  copied: '복사됨 ✓',
  copy_failed: '복사 실패',
  unknown_error: '알 수 없는 오류',
  no_bg_response: '백그라운드 응답 없음',
  row_daemon: 'daemon 실행 중',
  row_ext: '확장 프로그램 준비됨',
  row_page: '활성 탭 디버그 가능',
  test_ok: 'Webflow Bridge가 준비되었습니다 — 확장 프로그램이 {browser}에서 실행 중입니다.\n다음 단계: 스크립트나 AI 에이전트에서 http://127.0.0.1:10086/command로 POST를 보내면 이 탭을 구동할 수 있습니다(프로토콜: 저장소 docs/HTTP_API.md 참조)',
  note_ext_down: '확장 프로그램이 중지된 동안에는 확인할 수 없습니다. 위 단계에서 확장 프로그램을 다시 로드하세요.',
  daemon_lead: '로컬 daemon을 시작하세요 — 두 방법 중 하나:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'GitHub에서 Webflow Bridge 보기',
  ext_fix_1: '<b>{browser}</b>의 확장 프로그램 관리 페이지를 열고 <b>개발자 모드</b>가 켜져 있는지 확인하세요.',
  ext_fix_2: '<b>Webflow Bridge</b>를 찾아 <b>다시 로드</b> 버튼을 클릭하세요.',
  page_fix_switch: '브라우저를 일반 웹페이지 탭으로 전환하세요 — http:// 또는 https:// 사이트.',
  page_fix_restricted: 'chrome:// 페이지, Chrome 웹 스토어, 새 탭 페이지는 구동할 수 없습니다.',
  page_fix_restricted_edge: 'edge:// 페이지, Edge 부가 기능 스토어, 새 탭 페이지는 구동할 수 없습니다.',
  page_fix_devtools: '다른 디버거(보통 DevTools(F12))가 활성 탭에 연결되어 있습니다. 닫으면 위 상태가 자동으로 업데이트됩니다.',
  page_fix_generic: '현재 활성 탭을 구동할 수 없습니다. 일반 http(s) 페이지로 전환하세요. 계속 실패하면 탭의 DevTools(F12)를 닫고 아래 명령으로 확장 프로그램을 다시 로드한 후 다시 시도하세요.'
},

'fr': {
  checking: 'Vérification…',
  inactive: 'Inactif',
  reason_daemon_down: 'Le daemon n’est pas démarré',
  reason_daemon_busy: 'Le daemon est déjà utilisé par un autre navigateur',
  active: 'Actif',
  disconnected: 'Déconnecté',
  disconnect: 'Déconnecter',
  reconnect: 'Reconnecter',
  wizard_title: 'Checklist d’activation',
  copy: 'Copier',
  copied: 'Copié ✓',
  copy_failed: 'Échec de la copie',
  unknown_error: 'erreur inconnue',
  no_bg_response: 'pas de réponse de l’arrière-plan',
  row_daemon: 'daemon en cours d’exécution',
  row_ext: 'Extension prête',
  row_page: 'Onglet actif débogable',
  test_ok: 'Webflow Bridge est prêt — l’extension s’exécute dans {browser}.\nÉtape suivante : envoyez un POST depuis votre script ou agent IA vers http://127.0.0.1:10086/command pour piloter cet onglet (protocole : voir docs/HTTP_API.md dans le dépôt)',
  note_ext_down: 'Impossible de vérifier tant que l’extension est arrêtée — rechargez-la ci-dessus.',
  daemon_lead: 'Démarrez le daemon — au choix :',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge sur GitHub',
  ext_fix_1: 'Ouvrez la page des extensions de <b>{browser}</b> et assurez-vous que le <b>mode développeur</b> est activé.',
  ext_fix_2: 'Trouvez <b>Webflow Bridge</b> et cliquez sur son bouton <b>Recharger</b>.',
  page_fix_switch: 'Passez le navigateur sur un onglet de page web normale — n’importe quel site http:// ou https://.',
  page_fix_restricted: 'Les pages chrome://, le Chrome Web Store et les pages de nouvel onglet ne peuvent pas être pilotées.',
  page_fix_restricted_edge: 'Les pages edge://, la boutique de modules Edge et les pages de nouvel onglet ne peuvent pas être pilotées.',
  page_fix_devtools: 'Un autre débogueur — généralement DevTools (F12) — est attaché à l’onglet actif. Fermez-le : le statut ci-dessus se met à jour automatiquement.',
  page_fix_generic: 'L’onglet actif ne peut pas être piloté pour le moment. Passez à une page http(s) normale ; si cela échoue toujours, fermez DevTools (F12) sur l’onglet, rechargez l’extension avec la commande ci-dessous et réessayez.'
},

'de': {
  checking: 'Prüfe…',
  inactive: 'Inaktiv',
  reason_daemon_down: 'Der Daemon läuft nicht',
  reason_daemon_busy: 'Der Daemon wird bereits von einem anderen Browser verwendet',
  active: 'Aktiv',
  disconnected: 'Getrennt',
  disconnect: 'Trennen',
  reconnect: 'Neu verbinden',
  wizard_title: 'Aktivierungs-Checkliste',
  copy: 'Kopieren',
  copied: 'Kopiert ✓',
  copy_failed: 'Kopieren fehlgeschlagen',
  unknown_error: 'unbekannter Fehler',
  no_bg_response: 'keine Antwort vom Hintergrund',
  row_daemon: 'Daemon läuft',
  row_ext: 'Erweiterung bereit',
  row_page: 'Aktiver Tab debug-fähig',
  test_ok: 'Webflow Bridge ist bereit — die Erweiterung läuft in {browser}.\nNächster Schritt: Senden Sie einen POST von Ihrem Skript oder AI-Agenten an http://127.0.0.1:10086/command, um diesen Tab zu steuern (Protokoll: siehe docs/HTTP_API.md im Repository)',
  note_ext_down: 'Prüfung nicht möglich, solange die Erweiterung nicht läuft — laden Sie sie oben neu.',
  daemon_lead: 'Daemon starten — eine der beiden Möglichkeiten:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge auf GitHub',
  ext_fix_1: 'Öffnen Sie die Erweiterungsseite von <b>{browser}</b> und stellen Sie sicher, dass der <b>Entwicklermodus</b> aktiviert ist.',
  ext_fix_2: 'Suchen Sie <b>Webflow Bridge</b> und klicken Sie auf dessen Schaltfläche <b>Neu laden</b>.',
  page_fix_switch: 'Wechseln Sie den Browser auf einen normalen Webseiten-Tab — jede http://- oder https://-Seite.',
  page_fix_restricted: 'chrome://-Seiten, der Chrome Web Store und neue-Tab-Seiten können nicht gesteuert werden.',
  page_fix_restricted_edge: 'edge://-Seiten, der Edge-Add-ons-Speicher und neue-Tab-Seiten können nicht gesteuert werden.',
  page_fix_devtools: 'Ein anderer Debugger — meist DevTools (F12) — ist am aktiven Tab angehängt. Schließen Sie ihn — der Status oben wird automatisch aktualisiert.',
  page_fix_generic: 'Der aktive Tab kann gerade nicht gesteuert werden. Wechseln Sie auf eine normale http(s)-Seite; falls es weiterhin fehlschlägt, schließen Sie DevTools (F12) auf dem Tab, laden Sie die Erweiterung mit dem unten stehenden Befehl neu und versuchen Sie es erneut.'
},

'es': {
  checking: 'Comprobando…',
  inactive: 'Inactivo',
  reason_daemon_down: 'El daemon no está en ejecución',
  reason_daemon_busy: 'Otro navegador ya está usando el daemon',
  active: 'Activo',
  disconnected: 'Desconectado',
  disconnect: 'Desconectar',
  reconnect: 'Reconectar',
  wizard_title: 'Lista de verificación de activación',
  copy: 'Copiar',
  copied: 'Copiado ✓',
  copy_failed: 'Error al copiar',
  unknown_error: 'error desconocido',
  no_bg_response: 'sin respuesta del fondo',
  row_daemon: 'daemon en ejecución',
  row_ext: 'Extensión lista',
  row_page: 'Pestaña activa depurable',
  test_ok: 'Webflow Bridge está listo: la extensión se ejecuta en {browser}.\nSiguiente paso: envía un POST desde tu script o agente de IA a http://127.0.0.1:10086/command para controlar esta pestaña (protocolo: ver docs/HTTP_API.md en el repositorio)',
  note_ext_down: 'No se puede comprobar mientras la extensión esté detenida; recárgala arriba.',
  daemon_lead: 'Inicia el daemon — elige una de las dos formas:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge en GitHub',
  ext_fix_1: 'Abre la página de extensiones de <b>{browser}</b> y asegúrate de que el <b>modo de desarrollador</b> esté activado.',
  ext_fix_2: 'Busca <b>Webflow Bridge</b> y haz clic en su botón <b>Recargar</b>.',
  page_fix_switch: 'Cambia el navegador a una pestaña de página web normal: cualquier sitio http:// o https://.',
  page_fix_restricted: 'Las páginas chrome://, Chrome Web Store y las páginas de pestaña nueva no se pueden controlar.',
  page_fix_restricted_edge: 'Las páginas edge://, Edge Add-ons store y las páginas de pestaña nueva no se pueden controlar.',
  page_fix_devtools: 'Hay otro depurador (normalmente DevTools [F12]) adjunto a la pestaña activa. Ciérralo: el estado de arriba se actualiza automáticamente.',
  page_fix_generic: 'La pestaña activa no se puede controlar ahora mismo. Cambia a una página http(s) normal; si sigue fallando, cierra DevTools (F12) en la pestaña, recarga la extensión con el comando de abajo e inténtalo de nuevo.'
},

'pt': {
  checking: 'Verificando…',
  inactive: 'Inativo',
  reason_daemon_down: 'O daemon não está em execução',
  reason_daemon_busy: 'O daemon já está em uso por outro navegador',
  active: 'Ativo',
  disconnected: 'Desconectado',
  disconnect: 'Desconectar',
  reconnect: 'Reconectar',
  wizard_title: 'Lista de verificação de ativação',
  copy: 'Copiar',
  copied: 'Copiado ✓',
  copy_failed: 'Falha ao copiar',
  unknown_error: 'erro desconhecido',
  no_bg_response: 'sem resposta do plano de fundo',
  row_daemon: 'daemon em execução',
  row_ext: 'Extensão pronta',
  row_page: 'Aba ativa depurável',
  test_ok: 'O Webflow Bridge está pronto — a extensão está em execução no {browser}.\nPróximo passo: envie um POST do seu script ou agente de IA para http://127.0.0.1:10086/command para acionar esta aba (protocolo: consulte docs/HTTP_API.md no repositório)',
  note_ext_down: 'Não é possível verificar enquanto a extensão estiver parada — recarregue-a acima.',
  daemon_lead: 'Inicie o daemon — escolha uma das formas:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge no GitHub',
  ext_fix_1: 'Abra a página de extensões do <b>{browser}</b> e certifique-se de que o <b>modo do desenvolvedor</b> está ativado.',
  ext_fix_2: 'Encontre <b>Webflow Bridge</b> e clique no botão <b>Recarregar</b>.',
  page_fix_switch: 'Mude o navegador para uma aba de página web normal — qualquer site http:// ou https://.',
  page_fix_restricted: 'Páginas chrome://, a Chrome Web Store e páginas de nova aba não podem ser acionadas.',
  page_fix_restricted_edge: 'Páginas edge://, a loja de complementos do Edge e páginas de nova aba não podem ser acionadas.',
  page_fix_devtools: 'Outro depurador — geralmente DevTools (F12) — está anexado à aba ativa. Feche-o — o status acima é atualizado automaticamente.',
  page_fix_generic: 'A aba ativa não pode ser acionada agora. Mude para uma página http(s) normal; se continuar falhando, feche o DevTools (F12) na aba, recarregue a extensão com o comando abaixo e tente novamente.'
},

'ru': {
  checking: 'Проверка…',
  inactive: 'Неактивен',
  reason_daemon_down: 'Служба daemon не запущена',
  reason_daemon_busy: 'daemon уже используется другим браузером',
  active: 'Активен',
  disconnected: 'Отключено',
  disconnect: 'Отключить',
  reconnect: 'Подключить снова',
  wizard_title: 'Чек-лист активации',
  copy: 'Копировать',
  copied: 'Скопировано ✓',
  copy_failed: 'Не удалось скопировать',
  unknown_error: 'неизвестная ошибка',
  no_bg_response: 'нет ответа от фона',
  row_daemon: 'daemon запущен',
  row_ext: 'Расширение готово',
  row_page: 'Активная вкладка доступна для отладки',
  test_ok: 'Webflow Bridge готов — расширение работает в {browser}.\nСледующий шаг: отправьте POST из своего скрипта или ИИ-агента на http://127.0.0.1:10086/command, чтобы управлять этой вкладкой (протокол — см. docs/HTTP_API.md в репозитории)',
  note_ext_down: 'Не удаётся проверить, пока расширение остановлено — перезагрузите его выше.',
  daemon_lead: 'Запустите daemon — любым из способов:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge на GitHub',
  ext_fix_1: 'Откройте страницу управления расширениями <b>{browser}</b> и убедитесь, что <b>режим разработчика</b> включён.',
  ext_fix_2: 'Найдите <b>Webflow Bridge</b> и нажмите кнопку <b>Перезагрузить</b>.',
  page_fix_switch: 'Переключите браузер на обычную вкладку веб-страницы — любой сайт http:// или https://.',
  page_fix_restricted: 'Страницы chrome://, Chrome Web Store и страницы новой вкладки не могут управляться.',
  page_fix_restricted_edge: 'Страницы edge://, магазин дополнений Edge и страницы новой вкладки не могут управляться.',
  page_fix_devtools: 'К активной вкладке подключён другой отладчик — обычно DevTools (F12). Закройте его — статус выше обновится автоматически.',
  page_fix_generic: 'Активную вкладку сейчас нельзя отлаживать. Переключитесь на обычную страницу http(s); если это не поможет, закройте DevTools (F12) на вкладке, перезагрузите расширение с помощью команды ниже и попробуйте ещё раз.'
},

'ar': {
  checking: 'جارٍ التحقق…',
  inactive: 'غير نشط',
  reason_daemon_down: 'الـ daemon لا يعمل',
  reason_daemon_busy: 'الـ daemon قيد الاستخدام من متصفح آخر',
  active: 'نشط',
  disconnected: 'غير متصل',
  disconnect: 'قطع الاتصال',
  reconnect: 'إعادة الاتصال',
  wizard_title: 'قائمة التحقق من التفعيل',
  copy: 'نسخ',
  copied: 'تم النسخ ✓',
  copy_failed: 'فشل النسخ',
  unknown_error: 'خطأ غير معروف',
  no_bg_response: 'لا استجابة من الخلفية',
  row_daemon: 'الدايمون يعمل',
  row_ext: 'الإضافة جاهزة',
  row_page: 'التبويب النشط قابل للتصحيح',
  test_ok: 'Webflow Bridge جاهز — الإضافة تعمل في {browser}.\nالخطوة التالية: أرسل طلب POST من السكربت أو وكيل الذكاء الاصطناعي إلى http://127.0.0.1:10086/command لتشغيل هذا التبويب (البروتوكول: راجع docs/HTTP_API.md في المستودع)',
  note_ext_down: 'لا يمكن التحقق بينما الإضافة متوقفة — أعد تحميلها أعلاه.',
  daemon_lead: 'شغّل الدايمون — اختر إحدى الطريقتين:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge على GitHub',
  ext_fix_1: 'افتح صفحة إضافات <b>{browser}</b> وتأكد من تفعيل <b>وضع المطوّر</b>.',
  ext_fix_2: 'ابحث عن <b>Webflow Bridge</b> وانقر على زر <b>إعادة التحميل</b>.',
  page_fix_switch: 'بدّل المتصفح إلى تبويب صفحة ويب عادية — أي موقع http:// أو https://.',
  page_fix_restricted: 'لا يمكن تشغيل صفحات chrome:// ومتجر Chrome وصفحات التبويب الجديد.',
  page_fix_restricted_edge: 'لا يمكن تشغيل صفحات edge:// ومتجر إضافات Edge وصفحات التبويب الجديد.',
  page_fix_devtools: 'مُرفَق مصحح آخر — عادة DevTools (F12) — بالتبويب النشط. أغلقه — سيتم تحديث الحالة أعلاه تلقائياً.',
  page_fix_generic: 'لا يمكن تشغيل التبويب النشط حالياً. انتقل إلى صفحة http(s) عادية؛ إذا استمر الفشل، أغلق DevTools (F12) في التبويب، وأعد تحميل الإضافة باستخدام الأمر أدناه وحاول مجدداً.'
},

'it': {
  checking: 'Verifica…',
  inactive: 'Inattivo',
  reason_daemon_down: 'Il daemon non è in esecuzione',
  reason_daemon_busy: 'Il daemon è già in uso da un altro browser',
  active: 'Attivo',
  disconnected: 'Disconnesso',
  disconnect: 'Disconnetti',
  reconnect: 'Riconnetti',
  wizard_title: 'Checklist di attivazione',
  copy: 'Copia',
  copied: 'Copiato ✓',
  copy_failed: 'Copia non riuscita',
  unknown_error: 'errore sconosciuto',
  no_bg_response: 'nessuna risposta dallo sfondo',
  row_daemon: 'daemon in esecuzione',
  row_ext: 'Estensione pronta',
  row_page: 'Scheda attiva debuggabile',
  test_ok: 'Webflow Bridge è pronto — l’estensione è in esecuzione in {browser}.\nPasso successivo: invia una POST dal tuo script o agente AI a http://127.0.0.1:10086/command per pilotare questa scheda (protocollo: vedi docs/HTTP_API.md nel repository)',
  note_ext_down: 'Impossibile verificare mentre l’estensione è ferma — ricaricala qui sopra.',
  daemon_lead: 'Avvia il daemon — scegli uno dei due modi:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge su GitHub',
  ext_fix_1: 'Apri la pagina delle estensioni di <b>{browser}</b> e assicurati che la <b>modalità sviluppatore</b> sia attiva.',
  ext_fix_2: 'Trova <b>Webflow Bridge</b> e fai clic sul pulsante <b>Ricarica</b>.',
  page_fix_switch: 'Passa il browser a una scheda con una normale pagina web — qualsiasi sito http:// o https://.',
  page_fix_restricted: 'Le pagine chrome://, il Chrome Web Store e le pagine di nuova scheda non possono essere pilotate.',
  page_fix_restricted_edge: 'Le pagine edge://, lo store dei componenti aggiuntivi di Edge e le pagine di nuova scheda non possono essere pilotate.',
  page_fix_devtools: 'Un altro debugger — di solito DevTools (F12) — è collegato alla scheda attiva. Chiudilo: lo stato qui sopra si aggiorna automaticamente.',
  page_fix_generic: 'La scheda attiva non può essere pilotata al momento. Passa a una normale pagina http(s); se continua a fallire, chiudi DevTools (F12) sulla scheda, ricarica l’estensione con il comando qui sotto e riprova.'
},

'vi': {
  checking: 'Đang kiểm tra…',
  inactive: 'Chưa kích hoạt',
  reason_daemon_down: 'daemon chưa chạy',
  reason_daemon_busy: 'daemon đang được trình duyệt khác dùng',
  active: 'Đã kích hoạt',
  disconnected: 'Đã ngắt kết nối',
  disconnect: 'Ngắt kết nối',
  reconnect: 'Kết nối lại',
  wizard_title: 'Danh sách kiểm tra kích hoạt',
  copy: 'Sao chép',
  copied: 'Đã sao chép ✓',
  copy_failed: 'Sao chép thất bại',
  unknown_error: 'lỗi không xác định',
  no_bg_response: 'không có phản hồi từ tiến trình nền',
  row_daemon: 'Daemon đang chạy',
  row_ext: 'Tiện ích đã sẵn sàng',
  row_page: 'Thẻ hiện tại có thể gỡ lỗi',
  test_ok: 'Webflow Bridge đã sẵn sàng — tiện ích đang chạy trong {browser}.\nBước tiếp theo: gửi POST từ script hoặc AI agent của bạn tới http://127.0.0.1:10086/command để điều khiển thẻ này (giao thức: xem docs/HTTP_API.md trong kho mã nguồn)',
  note_ext_down: 'Không kiểm tra được khi tiện ích đang tắt — hãy tải lại tiện ích ở trên.',
  daemon_lead: 'Khởi động daemon cục bộ — chọn một trong hai cách:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge trên GitHub',
  ext_fix_1: 'Mở trang quản lý tiện ích của <b>{browser}</b> và bật <b>Chế độ nhà phát triển</b>.',
  ext_fix_2: 'Tìm <b>Webflow Bridge</b> rồi bấm nút <b>Tải lại</b>.',
  page_fix_switch: 'Chuyển trình duyệt sang một thẻ trang web bình thường — bất kỳ trang http:// hoặc https:// nào.',
  page_fix_restricted: 'Không điều khiển được các trang chrome://, Chrome Web Store và trang thẻ mới.',
  page_fix_restricted_edge: 'Không điều khiển được các trang edge://, cửa hàng tiện ích Edge và trang thẻ mới.',
  page_fix_devtools: 'Một trình gỡ lỗi khác — thường là DevTools (F12) — đang gắn vào thẻ hiện tại. Hãy đóng nó; trạng thái ở trên sẽ tự cập nhật.',
  page_fix_generic: 'Hiện chưa điều khiển được thẻ đang mở. Hãy chuyển sang một trang http(s) bình thường; nếu vẫn lỗi, đóng DevTools (F12) trên thẻ đó, rồi tải lại tiện ích bằng lệnh bên dưới và thử lại.'
},

'th': {
  checking: 'กำลังตรวจสอบ…',
  inactive: 'ยังไม่เปิดใช้งาน',
  reason_daemon_down: 'daemon ยังไม่ทำงาน',
  reason_daemon_busy: 'daemon ถูกเบราว์เซอร์อื่นใช้งานอยู่',
  active: 'เปิดใช้งานแล้ว',
  disconnected: 'ตัดการเชื่อมต่อแล้ว',
  disconnect: 'ตัดการเชื่อมต่อ',
  reconnect: 'เชื่อมต่อใหม่',
  wizard_title: 'รายการตรวจสอบการเปิดใช้งาน',
  copy: 'คัดลอก',
  copied: 'คัดลอกแล้ว ✓',
  copy_failed: 'คัดลอกไม่สำเร็จ',
  unknown_error: 'ข้อผิดพลาดที่ไม่ทราบสาเหตุ',
  no_bg_response: 'ไม่มีการตอบกลับจากโปรเซสเบื้องหลัง',
  row_daemon: 'Daemon กำลังทำงาน',
  row_ext: 'ส่วนขยายพร้อมใช้งาน',
  row_page: 'แท็บปัจจุบันสามารถดีบักได้',
  test_ok: 'Webflow Bridge พร้อมใช้งานแล้ว — ส่วนขยายกำลังทำงานใน {browser}\nขั้นตอนถัดไป: ส่ง POST จากสคริปต์หรือ AI agent ของคุณไปที่ http://127.0.0.1:10086/command เพื่อควบคุมแท็บนี้ (โปรโตคอล: ดู docs/HTTP_API.md ในรีโป)',
  note_ext_down: 'ตรวจสอบไม่ได้ขณะส่วนขยายหยุดทำงาน — โหลดส่วนขยายใหม่ตามด้านบน',
  daemon_lead: 'เริ่ม daemon ในเครื่อง — เลือกวิธีใดวิธีหนึ่ง:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge บน GitHub',
  ext_fix_1: 'เปิดหน้าจัดการส่วนขยายของ <b>{browser}</b> และตรวจสอบว่าเปิด <b>โหมดนักพัฒนา</b> แล้ว',
  ext_fix_2: 'ค้นหา <b>Webflow Bridge</b> แล้วคลิกปุ่ม <b>โหลดใหม่</b>',
  page_fix_switch: 'สลับไปที่แท็บเว็บเพจปกติ — เว็บ http:// หรือ https:// ใดก็ได้',
  page_fix_restricted: 'หน้า chrome://, Chrome Web Store และหน้าแท็บใหม่ควบคุมไม่ได้',
  page_fix_restricted_edge: 'หน้า edge://, ร้านส่วนเสริม Edge และหน้าแท็บใหม่ควบคุมไม่ได้',
  page_fix_devtools: 'มีตัวดีบักอื่น — ปกติคือ DevTools (F12) — เชื่อมอยู่กับแท็บปัจจุบัน ปิดมันแล้วสถานะด้านบนจะอัปเดตอัตโนมัติ',
  page_fix_generic: 'ตอนนี้ยังควบคุมแท็บที่เปิดอยู่ไม่ได้ สลับไปที่หน้า http(s) ปกติ ถ้ายังไม่สำเร็จ ให้ปิด DevTools (F12) บนแท็บนั้น แล้วโหลดส่วนขยายใหม่ด้วยคำสั่งด้านล่างแล้วลองอีกครั้ง'
},

'id': {
  checking: 'Memeriksa…',
  inactive: 'Belum aktif',
  reason_daemon_down: 'daemon belum berjalan',
  reason_daemon_busy: 'daemon sedang dipakai browser lain',
  active: 'Aktif',
  disconnected: 'Terputus',
  disconnect: 'Putuskan',
  reconnect: 'Sambungkan lagi',
  wizard_title: 'Daftar periksa aktivasi',
  copy: 'Salin',
  copied: 'Tersalin ✓',
  copy_failed: 'Gagal menyalin',
  unknown_error: 'kesalahan tidak diketahui',
  no_bg_response: 'tidak ada respons dari proses latar',
  row_daemon: 'Daemon sedang berjalan',
  row_ext: 'Ekstensi siap',
  row_page: 'Tab saat ini dapat di-debug',
  test_ok: 'Webflow Bridge siap — ekstensi berjalan di {browser}.\nLangkah berikutnya: kirim POST dari skrip atau AI agent Anda ke http://127.0.0.1:10086/command untuk mengendalikan tab ini (protokol: lihat docs/HTTP_API.md di repositori)',
  note_ext_down: 'Tidak bisa memeriksa saat ekstensi mati — muat ulang ekstensi di atas.',
  daemon_lead: 'Jalankan daemon lokal — pilih salah satu cara:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'Webflow Bridge di GitHub',
  ext_fix_1: 'Buka halaman ekstensi <b>{browser}</b> dan pastikan <b>Mode pengembang</b> aktif.',
  ext_fix_2: 'Temukan <b>Webflow Bridge</b> lalu klik tombol <b>Muat ulang</b>.',
  page_fix_switch: 'Pindah browser ke tab halaman web biasa — situs http:// atau https:// apa pun.',
  page_fix_restricted: 'Halaman chrome://, Chrome Web Store, dan halaman tab baru tidak bisa dikendalikan.',
  page_fix_restricted_edge: 'Halaman edge://, toko Add-on Edge, dan halaman tab baru tidak bisa dikendalikan.',
  page_fix_devtools: 'Ada debugger lain — biasanya DevTools (F12) — yang terpasang di tab aktif. Tutup debugger itu; status di atas akan diperbarui otomatis.',
  page_fix_generic: 'Tab aktif belum bisa dikendalikan saat ini. Pindah ke halaman http(s) biasa; jika masih gagal, tutup DevTools (F12) di tab tersebut, lalu muat ulang ekstensi dengan perintah di bawah dan coba lagi.'
},

'hi': {
  checking: 'जाँच हो रही है…',
  inactive: 'निष्क्रिय',
  reason_daemon_down: 'daemon चल नहीं रहा',
  reason_daemon_busy: 'daemon किसी दूसरे ब्राउज़र में उपयोग में है',
  active: 'सक्रिय',
  disconnected: 'डिस्कनेक्ट हो गया',
  disconnect: 'डिस्कनेक्ट करें',
  reconnect: 'फिर कनेक्ट करें',
  wizard_title: 'सक्रिय करने की जाँच सूची',
  copy: 'कॉपी करें',
  copied: 'कॉपी हो गया ✓',
  copy_failed: 'कॉपी नहीं हो सका',
  unknown_error: 'अज्ञात त्रुटि',
  no_bg_response: 'बैकग्राउंड से कोई जवाब नहीं',
  row_daemon: 'Daemon चल रहा है',
  row_ext: 'एक्सटेंशन तैयार है',
  row_page: 'मौजूदा टैब डीबग किया जा सकता है',
  test_ok: 'Webflow Bridge तैयार है — एक्सटेंशन {browser} में चल रहा है।\nअगला कदम: अपनी स्क्रिप्ट या AI agent से http://127.0.0.1:10086/command पर POST भेजें और इस टैब को चलाएँ (प्रोटोकॉल: रेपो की docs/HTTP_API.md देखें)',
  note_ext_down: 'एक्सटेंशन बंद रहने पर जाँच नहीं हो सकती — ऊपर दिए तरीके से एक्सटेंशन फिर लोड करें।',
  daemon_lead: 'लोकल daemon शुरू करें — दो में से कोई भी तरीका चुनें:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  project_link: 'GitHub पर Webflow Bridge',
  ext_fix_1: '<b>{browser}</b> का एक्सटेंशन पेज खोलें और देखें कि <b>डेवलपर मोड</b> चालू है।',
  ext_fix_2: '<b>Webflow Bridge</b> ढूँढ़ें और उसका <b>फिर लोड करें</b> बटन दबाएँ।',
  page_fix_switch: 'ब्राउज़र को किसी सामान्य वेबपेज टैब पर ले जाएँ — कोई भी http:// या https:// साइट।',
  page_fix_restricted: 'chrome:// पेज, Chrome Web Store और नए टैब पेज नहीं चलाए जा सकते।',
  page_fix_restricted_edge: 'edge:// पेज, Edge Add-ons स्टोर और नए टैब पेज नहीं चलाए जा सकते।',
  page_fix_devtools: 'मौजूदा टैब से कोई दूसरा डीबगर — आम तौर पर DevTools (F12) — जुड़ा है। उसे बंद करें, ऊपर की स्थिति अपने आप अपडेट हो जाएगी।',
  page_fix_generic: 'अभी मौजूदा टैब नहीं चलाया जा सकता। किसी सामान्य http(s) पेज पर जाएँ; फिर भी दिक्कत हो तो उस टैब पर DevTools (F12) बंद करें, नीचे दिए कमांड से एक्सटेंशन फिर लोड करें और दोबारा कोशिश करें।'
}

  };

  // ----- language detection (exact -> parent/region mapping -> en) -----
  function detectLang() {
    var raw = '';
    try { raw = String(navigator.language || ''); } catch (e) { raw = ''; }
    if (!raw) {
      try {
        if (typeof browser !== 'undefined' && browser.i18n && browser.i18n.getUILanguage) {
          raw = String(browser.i18n.getUILanguage() || '');
        }
      } catch (e) { /* keep empty -> en */ }
    }
    raw = String(raw).replace(/_/g, '-').toLowerCase();
    if (!raw) return 'en';
    if (raw === 'zh' || raw.indexOf('zh-') === 0) {
      // zh-TW / zh-HK / zh-MO -> Traditional; everything else zh -> Simplified.
      if (raw === 'zh-tw' || raw === 'zh-hk' || raw === 'zh-mo') return 'zh-TW';
      return 'zh-CN';
    }
    var base = raw.split('-')[0];
    if (base === 'in') base = 'id';        // legacy code for Indonesian
    return MESSAGES[base] ? base : 'en';   // pt-BR/pt-PT/pt -> 'pt' via base
  }

  var lang = detectLang();

  function t(key, vars) {
    var s = null;
    var v = MESSAGES[lang];
    if (v && Object.prototype.hasOwnProperty.call(v, key)) s = v[key];
    if (s == null || s === '') s = MESSAGES.en[key];     // never blank
    if (s == null) s = key;
    if (vars) {
      s = String(s).replace(/\{([a-zA-Z0-9_]+)\}/g, function (m, k) {
        return Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m;
      });
    }
    return s;
  }

  // ----- one-shot static pass over the markup -----
  function applyStatic() {
    var d = document.documentElement;
    if (d) {
      d.lang = lang;
      d.setAttribute('dir', lang === 'ar' ? 'rtl' : 'ltr');
    }
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var k = el.getAttribute('data-i18n');
      if (k) el.textContent = t(k);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      var k = el.getAttribute('data-i18n-title');
      if (k) el.setAttribute('title', t(k));
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      var k = el.getAttribute('data-i18n-placeholder');
      if (k) el.setAttribute('placeholder', t(k));
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyStatic);
  } else {
    applyStatic();
  }

  window.WBF_I18N = { lang: lang, t: t };
})();
