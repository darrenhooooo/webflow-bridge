/* Webflow Bridge popup — self-contained i18n (Chrome / Edge version).
 *
 * 12 languages, auto-detected from navigator.language (browser.i18n.
 * getUILanguage is used as a fallback where present). Matching: exact
 * region match wins (zh-HK -> Traditional), then a parent-language /
 * region mapping (zh without region -> Simplified, pt-BR/pt-PT -> pt,
 * en-US -> en), anything unknown -> English.
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
  active: 'Active',
  wizard_title: 'Activation checklist',
  recheck: 'Re-check',
  copy: 'Copy',
  copied: 'Copied ✓',
  copy_failed: 'Copy failed',
  unknown_error: 'unknown error',
  no_bg_response: 'no response from background',
  row_daemon: 'Daemon running',
  row_ext: 'Extension ready',
  row_page: 'Active tab debug-able',
  test_ok: '✓ Webflow Bridge is ready — commands can be executed on the current page\nNext step: send a POST from your script or AI agent to http://127.0.0.1:10086/command to drive this tab (protocol: see docs/HTTP_API.md in the repo)',
  note_ext_down: 'Can’t check while the extension is down — reload it above, then Re-check.',
  note_daemon_pending: 'Start the daemon above — the active tab is probed once it is running.',
  daemon_lead: 'Start the daemon — pick either way:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  daemon_fix_wait: 'Wait for the <b>“Webflow Bridge daemon started”</b> banner, then press <b>Re-check</b> below.',
  ext_fix_1: 'Open <code>{ext_url}</code> and make sure <b>Developer mode</b> is on.',
  ext_fix_2: 'Find <b>Webflow Bridge</b> and click its <b>Reload</b> button.',
  press_recheck: 'Then press <b>Re-check</b> below.',
  page_fix_switch: 'Switch the browser to a normal webpage tab — any http:// or https:// site.',
  page_fix_restricted: 'chrome:// pages, the Chrome Web Store and new-tab pages can’t be driven.',
  page_fix_restricted_edge: 'edge:// pages, the Edge Add-ons store and new-tab pages can’t be driven.',
  page_fix_devtools: 'Another debugger — usually DevTools (F12) — is attached to the active tab. Close it, then press <b>Re-check</b> below.',
  page_fix_generic: 'The active tab can’t be driven right now. Switch to a normal http(s) page; if it keeps failing, close DevTools (F12) on the tab, reload the extension at <code>{ext_url}</code> and try again.'
},

'zh-CN': {
  checking: '检测中…',
  inactive: '未激活',
  active: '已激活',
  wizard_title: '激活清单',
  recheck: '重新检查',
  copy: '复制',
  copied: '已复制 ✓',
  copy_failed: '复制失败',
  unknown_error: '未知错误',
  no_bg_response: '后台无响应',
  row_daemon: 'Daemon 运行中',
  row_ext: '扩展已就绪',
  row_page: '当前标签页可调试',
  test_ok: '✓ Webflow Bridge 已就绪 — 可在当前页面执行命令\n下一步：从你的脚本或 AI agent 向 http://127.0.0.1:10086/command 发送 POST，即可驱动此标签页（协议见仓库 docs/HTTP_API.md）',
  note_ext_down: '扩展不可用时无法检查 — 请按上方步骤重新加载扩展后再检查。',
  note_daemon_pending: '先启动上方 daemon — 运行后即可检测当前标签页。',
  daemon_lead: '启动本地 daemon — 任选一种方式：',
  cmd_python: 'Python：',
  cmd_uv: 'uv：',
  daemon_fix_wait: '看到“Webflow Bridge daemon started”横幅后，点击下方<b>重新检查</b>。',
  ext_fix_1: '打开 <code>{ext_url}</code>，确认已开启<b>开发者模式</b>。',
  ext_fix_2: '找到 <b>Webflow Bridge</b>，点击其<b>重新加载</b>按钮。',
  press_recheck: '然后点击下方<b>重新检查</b>。',
  page_fix_switch: '将浏览器切换到普通网页标签页 — 任意 http:// 或 https:// 网站。',
  page_fix_restricted: 'chrome:// 页面、Chrome 应用商店和新标签页无法驱动。',
  page_fix_restricted_edge: 'edge:// 页面、Edge 加载项商店和新标签页无法驱动。',
  page_fix_devtools: '当前标签页已被另一个调试器 — 通常是 DevTools（F12）— 附加。关闭它，然后点击下方<b>重新检查</b>。',
  page_fix_generic: '当前标签页暂时无法驱动。请切换到普通 http(s) 页面；若仍失败，关闭该标签页上的 DevTools（F12），在 <code>{ext_url}</code> 重新加载扩展后再试。'
},

'zh-TW': {
  checking: '檢查中…',
  inactive: '未啟用',
  active: '已啟用',
  wizard_title: '啟用清單',
  recheck: '重新檢查',
  copy: '複製',
  copied: '已複製 ✓',
  copy_failed: '複製失敗',
  unknown_error: '未知錯誤',
  no_bg_response: '背景無回應',
  row_daemon: 'Daemon 執行中',
  row_ext: '擴充功能已就緒',
  row_page: '目前分頁可除錯',
  test_ok: '✓ Webflow Bridge 已就緒 — 可在目前頁面執行命令\n下一步：從你的腳本或 AI agent 向 http://127.0.0.1:10086/command 傳送 POST，即可驅動此分頁（協定見儲存庫 docs/HTTP_API.md）',
  note_ext_down: '擴充功能無法使用時無法檢查 — 請依上方步驟重新載入擴充功能後再檢查。',
  note_daemon_pending: '請先啟動上方的 daemon — 啟動後即可檢測目前分頁。',
  daemon_lead: '啟動本機 daemon — 任選一種方式：',
  cmd_python: 'Python：',
  cmd_uv: 'uv：',
  daemon_fix_wait: '看到「Webflow Bridge daemon started」橫幅後，點擊下方<b>重新檢查</b>。',
  ext_fix_1: '開啟 <code>{ext_url}</code>，確認已開啟<b>開發人員模式</b>。',
  ext_fix_2: '找到 <b>Webflow Bridge</b>，點擊其<b>重新載入</b>按鈕。',
  press_recheck: '然後點擊下方<b>重新檢查</b>。',
  page_fix_switch: '將瀏覽器切換到一般網頁分頁 — 任意 http:// 或 https:// 網站。',
  page_fix_restricted: 'chrome:// 頁面、Chrome 線上應用程式商店與新分頁無法驅動。',
  page_fix_restricted_edge: 'edge:// 頁面、Edge 附加元件商店與新分頁無法驅動。',
  page_fix_devtools: '目前分頁已被另一個偵錯工具 — 通常是 DevTools（F12）— 附加。關閉它，然後點擊下方<b>重新檢查</b>。',
  page_fix_generic: '目前分頁暫時無法驅動。請切換到一般 http(s) 頁面；若仍失敗，關閉該分頁上的 DevTools（F12），在 <code>{ext_url}</code> 重新載入擴充功能後再試。'
},

'ja': {
  checking: '確認中…',
  inactive: '未アクティブ',
  active: 'アクティブ',
  wizard_title: 'アクティブ化チェックリスト',
  recheck: '再チェック',
  copy: 'コピー',
  copied: 'コピーしました ✓',
  copy_failed: 'コピーに失敗しました',
  unknown_error: '不明なエラー',
  no_bg_response: 'バックグラウンドからの応答がありません',
  row_daemon: 'daemon 実行中',
  row_ext: '拡張機能の準備完了',
  row_page: 'アクティブなタブはデバッグ可能',
  test_ok: '✓ Webflow Bridge は準備完了です — 現在のページでコマンドを実行できます\n次のステップ：スクリプトまたは AI エージェントから http://127.0.0.1:10086/command へ POST を送信すると、このタブを操作できます（プロトコルはリポジトリの docs/HTTP_API.md を参照）',
  note_ext_down: '拡張機能が停止中は確認できません — 上記の手順で拡張機能を再読み込みしてから再チェックしてください。',
  note_daemon_pending: '上記の daemon を起動してください — 起動後にアクティブなタブを確認します。',
  daemon_lead: 'ローカル daemon を起動 — どちらかの方法で：',
  cmd_python: 'Python：',
  cmd_uv: 'uv：',
  daemon_fix_wait: '“Webflow Bridge daemon started” のバナーが表示されたら、下の<b>再チェック</b>を押してください。',
  ext_fix_1: '<code>{ext_url}</code> を開き、<b>デベロッパー モード</b>をオンにしてください。',
  ext_fix_2: '<b>Webflow Bridge</b> を探して<b>再読み込み</b>ボタンをクリックしてください。',
  press_recheck: 'その後、下の<b>再チェック</b>を押してください。',
  page_fix_switch: 'ブラウザを通常のウェブページのタブに切り替えてください — http:// や https:// のサイト。',
  page_fix_restricted: 'chrome:// ページ、Chrome ウェブストア、新規タブページは操作できません。',
  page_fix_restricted_edge: 'edge:// ページ、Edge アドオンストア、新規タブページは操作できません。',
  page_fix_devtools: '別のデバッガー（通常は DevTools（F12））がアクティブなタブにアタッチされています。閉じてから、下の<b>再チェック</b>を押してください。',
  page_fix_generic: '現在アクティブなタブを操作できません。通常の http(s) ページに切り替えてください。それでも失敗する場合は、タブの DevTools（F12）を閉じ、<code>{ext_url}</code> で拡張機能を再読み込みしてもう一度お試しください。'
},

'ko': {
  checking: '확인 중…',
  inactive: '비활성',
  active: '활성',
  wizard_title: '활성화 체크리스트',
  recheck: '다시 확인',
  copy: '복사',
  copied: '복사됨 ✓',
  copy_failed: '복사 실패',
  unknown_error: '알 수 없는 오류',
  no_bg_response: '백그라운드 응답 없음',
  row_daemon: 'daemon 실행 중',
  row_ext: '확장 프로그램 준비됨',
  row_page: '활성 탭 디버그 가능',
  test_ok: '✓ Webflow Bridge가 준비되었습니다 — 현재 페이지에서 명령을 실행할 수 있습니다\n다음 단계: 스크립트나 AI 에이전트에서 http://127.0.0.1:10086/command로 POST를 보내면 이 탭을 구동할 수 있습니다(프로토콜: 저장소 docs/HTTP_API.md 참조)',
  note_ext_down: '확장 프로그램이 중지된 동안에는 확인할 수 없습니다. 위 단계에서 확장 프로그램을 다시 로드한 후 다시 확인하세요.',
  note_daemon_pending: '위의 daemon을 먼저 시작하세요. 실행되면 활성 탭을 확인합니다.',
  daemon_lead: '로컬 daemon을 시작하세요 — 두 방법 중 하나:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  daemon_fix_wait: '“Webflow Bridge daemon started” 배너가 보이면 아래의 <b>다시 확인</b>을 누르세요.',
  ext_fix_1: '<code>{ext_url}</code>을 열고 <b>개발자 모드</b>가 켜져 있는지 확인하세요.',
  ext_fix_2: '<b>Webflow Bridge</b>를 찾아 <b>다시 로드</b> 버튼을 클릭하세요.',
  press_recheck: '그런 다음 아래의 <b>다시 확인</b>을 누르세요.',
  page_fix_switch: '브라우저를 일반 웹페이지 탭으로 전환하세요 — http:// 또는 https:// 사이트.',
  page_fix_restricted: 'chrome:// 페이지, Chrome 웹 스토어, 새 탭 페이지는 구동할 수 없습니다.',
  page_fix_restricted_edge: 'edge:// 페이지, Edge 부가 기능 스토어, 새 탭 페이지는 구동할 수 없습니다.',
  page_fix_devtools: '다른 디버거(보통 DevTools(F12))가 활성 탭에 연결되어 있습니다. 닫은 후 아래의 <b>다시 확인</b>을 누르세요.',
  page_fix_generic: '현재 활성 탭을 구동할 수 없습니다. 일반 http(s) 페이지로 전환하세요. 계속 실패하면 탭의 DevTools(F12)를 닫고 <code>{ext_url}</code>에서 확장 프로그램을 다시 로드한 후 다시 시도하세요.'
},

'fr': {
  checking: 'Vérification…',
  inactive: 'Inactif',
  active: 'Actif',
  wizard_title: 'Checklist d’activation',
  recheck: 'Re-vérifier',
  copy: 'Copier',
  copied: 'Copié ✓',
  copy_failed: 'Échec de la copie',
  unknown_error: 'erreur inconnue',
  no_bg_response: 'pas de réponse de l’arrière-plan',
  row_daemon: 'daemon en cours d’exécution',
  row_ext: 'Extension prête',
  row_page: 'Onglet actif débogable',
  test_ok: '✓ Webflow Bridge est prêt — vous pouvez exécuter des commandes sur la page actuelle\nÉtape suivante : envoyez un POST depuis votre script ou agent IA vers http://127.0.0.1:10086/command pour piloter cet onglet (protocole : voir docs/HTTP_API.md dans le dépôt)',
  note_ext_down: 'Impossible de vérifier tant que l’extension est arrêtée — rechargez-la ci-dessus, puis re-vérifiez.',
  note_daemon_pending: 'Démarrez le daemon ci-dessus — l’onglet actif sera vérifié une fois celui-ci lancé.',
  daemon_lead: 'Démarrez le daemon — au choix :',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  daemon_fix_wait: 'Attendez la bannière « Webflow Bridge daemon started », puis appuyez sur <b>Re-vérifier</b> ci-dessous.',
  ext_fix_1: 'Ouvrez <code>{ext_url}</code> et assurez-vous que le <b>mode développeur</b> est activé.',
  ext_fix_2: 'Trouvez <b>Webflow Bridge</b> et cliquez sur son bouton <b>Recharger</b>.',
  press_recheck: 'Puis appuyez sur <b>Re-vérifier</b> ci-dessous.',
  page_fix_switch: 'Passez le navigateur sur un onglet de page web normale — n’importe quel site http:// ou https://.',
  page_fix_restricted: 'Les pages chrome://, le Chrome Web Store et les pages de nouvel onglet ne peuvent pas être pilotées.',
  page_fix_restricted_edge: 'Les pages edge://, la boutique de modules Edge et les pages de nouvel onglet ne peuvent pas être pilotées.',
  page_fix_devtools: 'Un autre débogueur — généralement DevTools (F12) — est attaché à l’onglet actif. Fermez-le, puis appuyez sur <b>Re-vérifier</b> ci-dessous.',
  page_fix_generic: 'L’onglet actif ne peut pas être piloté pour le moment. Passez à une page http(s) normale ; si cela échoue toujours, fermez DevTools (F12) sur l’onglet, rechargez l’extension dans <code>{ext_url}</code> et réessayez.'
},

'de': {
  checking: 'Prüfe…',
  inactive: 'Inaktiv',
  active: 'Aktiv',
  wizard_title: 'Aktivierungs-Checkliste',
  recheck: 'Erneut prüfen',
  copy: 'Kopieren',
  copied: 'Kopiert ✓',
  copy_failed: 'Kopieren fehlgeschlagen',
  unknown_error: 'unbekannter Fehler',
  no_bg_response: 'keine Antwort vom Hintergrund',
  row_daemon: 'Daemon läuft',
  row_ext: 'Erweiterung bereit',
  row_page: 'Aktiver Tab debug-fähig',
  test_ok: '✓ Webflow Bridge ist bereit — auf der aktuellen Seite können Befehle ausgeführt werden\nNächster Schritt: Senden Sie einen POST von Ihrem Skript oder AI-Agenten an http://127.0.0.1:10086/command, um diesen Tab zu steuern (Protokoll: siehe docs/HTTP_API.md im Repository)',
  note_ext_down: 'Prüfung nicht möglich, solange die Erweiterung nicht läuft — laden Sie sie oben neu und prüfen Sie erneut.',
  note_daemon_pending: 'Starten Sie zuerst den Daemon oben — der aktive Tab wird geprüft, sobald er läuft.',
  daemon_lead: 'Daemon starten — eine der beiden Möglichkeiten:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  daemon_fix_wait: 'Warten Sie auf das Banner „Webflow Bridge daemon started“, dann drücken Sie unten <b>Erneut prüfen</b>.',
  ext_fix_1: 'Öffnen Sie <code>{ext_url}</code> und stellen Sie sicher, dass der <b>Entwicklermodus</b> aktiviert ist.',
  ext_fix_2: 'Suchen Sie <b>Webflow Bridge</b> und klicken Sie auf dessen Schaltfläche <b>Neu laden</b>.',
  press_recheck: 'Drücken Sie anschließend unten <b>Erneut prüfen</b>.',
  page_fix_switch: 'Wechseln Sie den Browser auf einen normalen Webseiten-Tab — jede http://- oder https://-Seite.',
  page_fix_restricted: 'chrome://-Seiten, der Chrome Web Store und neue-Tab-Seiten können nicht gesteuert werden.',
  page_fix_restricted_edge: 'edge://-Seiten, der Edge-Add-ons-Speicher und neue-Tab-Seiten können nicht gesteuert werden.',
  page_fix_devtools: 'Ein anderer Debugger — meist DevTools (F12) — ist am aktiven Tab angehängt. Schließen Sie ihn und drücken Sie unten <b>Erneut prüfen</b>.',
  page_fix_generic: 'Der aktive Tab kann gerade nicht gesteuert werden. Wechseln Sie auf eine normale http(s)-Seite; falls es weiterhin fehlschlägt, schließen Sie DevTools (F12) auf dem Tab, laden Sie die Erweiterung unter <code>{ext_url}</code> neu und versuchen Sie es erneut.'
},

'es': {
  checking: 'Comprobando…',
  inactive: 'Inactivo',
  active: 'Activo',
  wizard_title: 'Lista de verificación de activación',
  recheck: 'Volver a comprobar',
  copy: 'Copiar',
  copied: 'Copiado ✓',
  copy_failed: 'Error al copiar',
  unknown_error: 'error desconocido',
  no_bg_response: 'sin respuesta del fondo',
  row_daemon: 'daemon en ejecución',
  row_ext: 'Extensión lista',
  row_page: 'Pestaña activa depurable',
  test_ok: '✓ Webflow Bridge está listo: puedes ejecutar comandos en la página actual\nSiguiente paso: envía un POST desde tu script o agente de IA a http://127.0.0.1:10086/command para controlar esta pestaña (protocolo: ver docs/HTTP_API.md en el repositorio)',
  note_ext_down: 'No se puede comprobar mientras la extensión esté detenida; recárgala arriba y vuelve a comprobar.',
  note_daemon_pending: 'Inicia el daemon de arriba: la pestaña activa se comprobará cuando esté en ejecución.',
  daemon_lead: 'Inicia el daemon — elige una de las dos formas:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  daemon_fix_wait: 'Espera el aviso «Webflow Bridge daemon started» y pulsa <b>Volver a comprobar</b> abajo.',
  ext_fix_1: 'Abre <code>{ext_url}</code> y asegúrate de que el <b>modo de desarrollador</b> esté activado.',
  ext_fix_2: 'Busca <b>Webflow Bridge</b> y haz clic en su botón <b>Recargar</b>.',
  press_recheck: 'Después pulsa <b>Volver a comprobar</b> abajo.',
  page_fix_switch: 'Cambia el navegador a una pestaña de página web normal: cualquier sitio http:// o https://.',
  page_fix_restricted: 'Las páginas chrome://, Chrome Web Store y las páginas de pestaña nueva no se pueden controlar.',
  page_fix_restricted_edge: 'Las páginas edge://, Edge Add-ons store y las páginas de pestaña nueva no se pueden controlar.',
  page_fix_devtools: 'Hay otro depurador (normalmente DevTools [F12]) adjunto a la pestaña activa. Ciérralo y pulsa <b>Volver a comprobar</b> abajo.',
  page_fix_generic: 'La pestaña activa no se puede controlar ahora mismo. Cambia a una página http(s) normal; si sigue fallando, cierra DevTools (F12) en la pestaña, recarga la extensión en <code>{ext_url}</code> e inténtalo de nuevo.'
},

'pt': {
  checking: 'Verificando…',
  inactive: 'Inativo',
  active: 'Ativo',
  wizard_title: 'Lista de verificação de ativação',
  recheck: 'Re-verificar',
  copy: 'Copiar',
  copied: 'Copiado ✓',
  copy_failed: 'Falha ao copiar',
  unknown_error: 'erro desconhecido',
  no_bg_response: 'sem resposta do plano de fundo',
  row_daemon: 'daemon em execução',
  row_ext: 'Extensão pronta',
  row_page: 'Aba ativa depurável',
  test_ok: '✓ O Webflow Bridge está pronto — é possível executar comandos na página atual\nPróximo passo: envie um POST do seu script ou agente de IA para http://127.0.0.1:10086/command para acionar esta aba (protocolo: consulte docs/HTTP_API.md no repositório)',
  note_ext_down: 'Não é possível verificar enquanto a extensão estiver parada — recarregue-a acima e verifique novamente.',
  note_daemon_pending: 'Inicie o daemon acima — a aba ativa será verificada quando ele estiver em execução.',
  daemon_lead: 'Inicie o daemon — escolha uma das formas:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  daemon_fix_wait: 'Aguarde a faixa «Webflow Bridge daemon started» e pressione <b>Re-verificar</b> abaixo.',
  ext_fix_1: 'Abra <code>{ext_url}</code> e certifique-se de que o <b>modo do desenvolvedor</b> está ativado.',
  ext_fix_2: 'Encontre <b>Webflow Bridge</b> e clique no botão <b>Recarregar</b>.',
  press_recheck: 'Depois pressione <b>Re-verificar</b> abaixo.',
  page_fix_switch: 'Mude o navegador para uma aba de página web normal — qualquer site http:// ou https://.',
  page_fix_restricted: 'Páginas chrome://, a Chrome Web Store e páginas de nova aba não podem ser acionadas.',
  page_fix_restricted_edge: 'Páginas edge://, a loja de complementos do Edge e páginas de nova aba não podem ser acionadas.',
  page_fix_devtools: 'Outro depurador — geralmente DevTools (F12) — está anexado à aba ativa. Feche-o e pressione <b>Re-verificar</b> abaixo.',
  page_fix_generic: 'A aba ativa não pode ser acionada agora. Mude para uma página http(s) normal; se continuar falhando, feche o DevTools (F12) na aba, recarregue a extensão em <code>{ext_url}</code> e tente novamente.'
},

'ru': {
  checking: 'Проверка…',
  inactive: 'Неактивен',
  active: 'Активен',
  wizard_title: 'Чек-лист активации',
  recheck: 'Проверить снова',
  copy: 'Копировать',
  copied: 'Скопировано ✓',
  copy_failed: 'Не удалось скопировать',
  unknown_error: 'неизвестная ошибка',
  no_bg_response: 'нет ответа от фона',
  row_daemon: 'daemon запущен',
  row_ext: 'Расширение готово',
  row_page: 'Активная вкладка доступна для отладки',
  test_ok: '✓ Webflow Bridge готов — на текущей странице можно выполнять команды\nСледующий шаг: отправьте POST из своего скрипта или ИИ-агента на http://127.0.0.1:10086/command, чтобы управлять этой вкладкой (протокол — см. docs/HTTP_API.md в репозитории)',
  note_ext_down: 'Не удаётся проверить, пока расширение остановлено — перезагрузите его выше и проверьте снова.',
  note_daemon_pending: 'Запустите daemon (команда выше) — активная вкладка будет проверена после его запуска.',
  daemon_lead: 'Запустите daemon — любым из способов:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  daemon_fix_wait: 'Дождитесь баннера «Webflow Bridge daemon started», затем нажмите <b>Проверить снова</b> ниже.',
  ext_fix_1: 'Откройте <code>{ext_url}</code> и убедитесь, что <b>режим разработчика</b> включён.',
  ext_fix_2: 'Найдите <b>Webflow Bridge</b> и нажмите кнопку <b>Перезагрузить</b>.',
  press_recheck: 'Затем нажмите <b>Проверить снова</b> ниже.',
  page_fix_switch: 'Переключите браузер на обычную вкладку веб-страницы — любой сайт http:// или https://.',
  page_fix_restricted: 'Страницы chrome://, Chrome Web Store и страницы новой вкладки не могут управляться.',
  page_fix_restricted_edge: 'Страницы edge://, магазин дополнений Edge и страницы новой вкладки не могут управляться.',
  page_fix_devtools: 'К активной вкладке подключён другой отладчик — обычно DevTools (F12). Закройте его и нажмите <b>Проверить снова</b> ниже.',
  page_fix_generic: 'Активную вкладку сейчас нельзя отлаживать. Переключитесь на обычную страницу http(s); если это не поможет, закройте DevTools (F12) на вкладке, перезагрузите расширение на <code>{ext_url}</code> и попробуйте ещё раз.'
},

'ar': {
  checking: 'جارٍ التحقق…',
  inactive: 'غير نشط',
  active: 'نشط',
  wizard_title: 'قائمة التحقق من التفعيل',
  recheck: 'إعادة التحقق',
  copy: 'نسخ',
  copied: 'تم النسخ ✓',
  copy_failed: 'فشل النسخ',
  unknown_error: 'خطأ غير معروف',
  no_bg_response: 'لا استجابة من الخلفية',
  row_daemon: 'الدايمون يعمل',
  row_ext: 'الإضافة جاهزة',
  row_page: 'التبويب النشط قابل للتصحيح',
  test_ok: '✓ Webflow Bridge جاهز — يمكن تنفيذ الأوامر في الصفحة الحالية\nالخطوة التالية: أرسل طلب POST من السكربت أو وكيل الذكاء الاصطناعي إلى http://127.0.0.1:10086/command لتشغيل هذا التبويب (البروتوكول: راجع docs/HTTP_API.md في المستودع)',
  note_ext_down: 'لا يمكن التحقق بينما الإضافة متوقفة — أعد تحميلها أعلاه ثم أعد التحقق.',
  note_daemon_pending: 'شغّل الدايمون أعلاه — سيتم فحص التبويب النشط بمجرد تشغيله.',
  daemon_lead: 'شغّل الدايمون — اختر إحدى الطريقتين:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  daemon_fix_wait: 'انتظر ظهور شريط "تم بدء تشغيل Webflow Bridge daemon"، ثم اضغط <b>إعادة التحقق</b> أدناه.',
  ext_fix_1: 'افتح <code>{ext_url}</code> وتأكد من تفعيل <b>وضع المطوّر</b>.',
  ext_fix_2: 'ابحث عن <b>Webflow Bridge</b> وانقر على زر <b>إعادة التحميل</b>.',
  press_recheck: 'ثم اضغط <b>إعادة التحقق</b> أدناه.',
  page_fix_switch: 'بدّل المتصفح إلى تبويب صفحة ويب عادية — أي موقع http:// أو https://.',
  page_fix_restricted: 'لا يمكن تشغيل صفحات chrome:// ومتجر Chrome وصفحات التبويب الجديد.',
  page_fix_restricted_edge: 'لا يمكن تشغيل صفحات edge:// ومتجر إضافات Edge وصفحات التبويب الجديد.',
  page_fix_devtools: 'مُرفَق مصحح آخر — عادة DevTools (F12) — بالتبويب النشط. أغلقه ثم اضغط <b>إعادة التحقق</b> أدناه.',
  page_fix_generic: 'لا يمكن تشغيل التبويب النشط حالياً. انتقل إلى صفحة http(s) عادية؛ إذا استمر الفشل، أغلق DevTools (F12) في التبويب، وأعد تحميل الإضافة من <code>{ext_url}</code> وحاول مجدداً.'
},

'it': {
  checking: 'Verifica…',
  inactive: 'Inattivo',
  active: 'Attivo',
  wizard_title: 'Checklist di attivazione',
  recheck: 'Ricontrolla',
  copy: 'Copia',
  copied: 'Copiato ✓',
  copy_failed: 'Copia non riuscita',
  unknown_error: 'errore sconosciuto',
  no_bg_response: 'nessuna risposta dallo sfondo',
  row_daemon: 'daemon in esecuzione',
  row_ext: 'Estensione pronta',
  row_page: 'Scheda attiva debuggabile',
  test_ok: '✓ Webflow Bridge è pronto — puoi eseguire comandi nella pagina corrente\nPasso successivo: invia una POST dal tuo script o agente AI a http://127.0.0.1:10086/command per pilotare questa scheda (protocollo: vedi docs/HTTP_API.md nel repository)',
  note_ext_down: 'Impossibile verificare mentre l’estensione è ferma — ricaricala qui sopra e ricontrolla.',
  note_daemon_pending: 'Avvia il daemon qui sopra: la scheda attiva verrà verificata quando è in esecuzione.',
  daemon_lead: 'Avvia il daemon — scegli uno dei due modi:',
  cmd_python: 'Python:',
  cmd_uv: 'uv:',
  daemon_fix_wait: 'Attendi il banner “Webflow Bridge daemon started”, quindi premi <b>Ricontrolla</b> qui sotto.',
  ext_fix_1: 'Apri <code>{ext_url}</code> e assicurati che la <b>modalità sviluppatore</b> sia attiva.',
  ext_fix_2: 'Trova <b>Webflow Bridge</b> e fai clic sul pulsante <b>Ricarica</b>.',
  press_recheck: 'Quindi premi <b>Ricontrolla</b> qui sotto.',
  page_fix_switch: 'Passa il browser a una scheda con una normale pagina web — qualsiasi sito http:// o https://.',
  page_fix_restricted: 'Le pagine chrome://, il Chrome Web Store e le pagine di nuova scheda non possono essere pilotate.',
  page_fix_restricted_edge: 'Le pagine edge://, lo store dei componenti aggiuntivi di Edge e le pagine di nuova scheda non possono essere pilotate.',
  page_fix_devtools: 'Un altro debugger — di solito DevTools (F12) — è collegato alla scheda attiva. Chiudilo e premi <b>Ricontrolla</b> qui sotto.',
  page_fix_generic: 'La scheda attiva non può essere pilotata al momento. Passa a una normale pagina http(s); se continua a fallire, chiudi DevTools (F12) sulla scheda, ricarica l’estensione su <code>{ext_url}</code> e riprova.'
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
