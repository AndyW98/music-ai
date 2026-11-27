/*
 * Call Switcher — a RoomOS macro for Cisco room devices (built for Room Bar Pro).
 *
 * Adds a "Calls" panel to the touch controller. Each call you're in shows up
 * as its own row; tap "Switch" to jump to it. Only the call you're viewing is
 * live: every other call is put on hold, so the device isn't receiving or
 * decoding video you can't see.
 *
 * Install: paste this file into the device's Macro Editor (or upload it from
 * Control Hub) and turn it on. The macro creates its own panel; no separate
 * UI Extensions file is needed.
 */
import xapi from 'xapi';

const DEFAULTS = {
  panelId: 'call_switcher',
  panelName: 'Calls',
  panelColor: '#1170CF',
  // When the call you're in ends and others are on hold, leave them on hold
  // and tell the user (false), or bring the oldest held call back (true).
  autoResumeOnHangUp: false,
  alertSeconds: 6,
};

const WIDGET_SWITCH = 'cs_switch_';
const WIDGET_END = 'cs_end_';
const WIDGET_NEW = 'cs_new';
const FEEDBACK_DIAL = 'cs_dial';

const CONNECTING = ['Dialling', 'Connecting', 'Ringing', 'EarlyMedia'];

function escapeXml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function errorText(err) {
  if (!err) return 'Unknown error';
  if (err.message) return err.message;
  if (err.data && err.data.Reason) return err.data.Reason;
  return String(err);
}

function createCallSwitcher(xapi, options = {}) {
  const config = { ...DEFAULTS, ...options };
  const calls = new Map(); // id -> raw status fields
  let switching = false;
  let lastPanelXml = '';

  // ---- call state -------------------------------------------------------

  function describe(raw) {
    const status = raw.Status || '';
    const held = status === 'OnHold' || raw.PlacedOnHold === 'True';
    return {
      id: String(raw.id),
      name: raw.DisplayName || raw.RemoteNumber || `Call ${raw.id}`,
      number: raw.RemoteNumber || '',
      type: raw.CallType || '',
      status,
      held,
      live: status === 'Connected' && !held,
      connecting: CONNECTING.includes(status),
    };
  }

  function getCalls() {
    return [...calls.values()].map(describe);
  }

  function getCall(id) {
    const raw = calls.get(String(id));
    return raw ? describe(raw) : undefined;
  }

  function liveCalls() {
    return getCalls().filter((c) => c.live);
  }

  function applyStatus(update) {
    // A single status event can be one call or a list of them.
    const updates = Array.isArray(update) ? update : [update];
    let endedLive = false;
    for (const u of updates) {
      if (!u || u.id === undefined) continue;
      const id = String(u.id);
      if (u.ghost === 'True') {
        const before = getCall(id);
        if (before && before.live) endedLive = true;
        calls.delete(id);
      } else {
        calls.set(id, { ...(calls.get(id) || {}), ...u, id });
      }
    }
    return endedLive;
  }

  // ---- actions ------------------------------------------------------------

  function alert(title, text) {
    return xapi.Command.UserInterface.Message.Alert.Display({
      Title: title,
      Text: text,
      Duration: config.alertSeconds,
    }).catch(() => {});
  }

  async function holdLiveCalls(exceptId) {
    for (const call of liveCalls()) {
      if (call.id !== exceptId) {
        await xapi.Command.Call.Hold({ CallId: call.id });
      }
    }
  }

  async function switchTo(id) {
    id = String(id);
    const target = getCall(id);
    if (!target || target.live || switching) return;
    switching = true;
    try {
      // Hold first, then resume, so two calls are never live at once.
      await holdLiveCalls(id);
      await xapi.Command.Call.Resume({ CallId: id });
    } catch (err) {
      await alert('Could not switch call', errorText(err));
    } finally {
      switching = false;
    }
  }

  async function endCall(id) {
    try {
      await xapi.Command.Call.Disconnect({ CallId: String(id) });
    } catch (err) {
      await alert('Could not end call', errorText(err));
    }
  }

  function askForNewCall() {
    return xapi.Command.UserInterface.Message.TextInput.Display({
      FeedbackId: FEEDBACK_DIAL,
      Title: 'New call',
      Text: 'Your current call will be put on hold.',
      Placeholder: 'Name, number or video address',
      InputType: 'SingleLine',
      SubmitText: 'Call',
    }).catch((err) => alert('Could not start a call', errorText(err)));
  }

  async function dial(address) {
    const number = String(address || '').trim();
    if (!number || switching) return;
    switching = true;
    try {
      await holdLiveCalls();
      await xapi.Command.Dial({ Number: number });
    } catch (err) {
      await alert('Call failed', errorText(err));
    } finally {
      switching = false;
    }
  }

  // ---- touch panel ------------------------------------------------------

  function button(id, name, size = 1) {
    return (
      `<Widget><WidgetId>${id}</WidgetId><Name>${escapeXml(name)}</Name>` +
      `<Type>Button</Type><Options>size=${size}</Options></Widget>`
    );
  }

  function text(id, value, size) {
    return (
      `<Widget><WidgetId>${id}</WidgetId><Name>${escapeXml(value)}</Name>` +
      `<Type>Text</Type><Options>size=${size};fontSize=normal;align=left</Options></Widget>`
    );
  }

  function callRow(call) {
    const state = call.live ? 'In call' : call.held ? 'On hold' : call.connecting ? 'Connecting…' : call.status;
    const widgets = [text(`cs_state_${call.id}`, state, 2)];
    if (call.held) widgets.push(button(`${WIDGET_SWITCH}${call.id}`, 'Switch'));
    widgets.push(button(`${WIDGET_END}${call.id}`, 'End'));
    return `<Row><Name>${escapeXml(call.name)}</Name>${widgets.join('')}</Row>`;
  }

  function panelXml() {
    const list = getCalls();
    const rows = list.length
      ? list.map(callRow).join('')
      : `<Row><Name></Name>${text('cs_empty', 'No calls', 4)}</Row>`;
    const newRow = `<Row><Name></Name>${button(WIDGET_NEW, 'New call', 4)}</Row>`;
    return (
      '<Extensions><Version>1.11</Version><Panel>' +
      `<PanelId>${config.panelId}</PanelId>` +
      '<Location>HomeScreenAndCallControls</Location>' +
      '<Icon>Handset</Icon>' +
      `<Color>${config.panelColor}</Color>` +
      `<Name>${escapeXml(config.panelName)}</Name>` +
      '<ActivityType>Custom</ActivityType>' +
      `<Page><Name>${escapeXml(config.panelName)}</Name>${rows}${newRow}` +
      '<PageId>cs_page</PageId><Options/></Page>' +
      '</Panel></Extensions>'
    );
  }

  async function render() {
    const xml = panelXml();
    if (xml === lastPanelXml) return;
    lastPanelXml = xml;
    try {
      await xapi.Command.UserInterface.Extensions.Panel.Save({ PanelId: config.panelId }, xml);
    } catch (err) {
      lastPanelXml = ''; // try again next time
      console.error('Call Switcher: could not save panel', errorText(err));
    }
  }

  // ---- events -------------------------------------------------------------

  async function onStatus(update) {
    const endedLive = applyStatus(update);
    await render();
    if (!endedLive || liveCalls().length) return;
    const held = getCalls().filter((c) => c.held);
    if (!held.length) return;
    if (config.autoResumeOnHangUp) {
      await switchTo(held[0].id);
    } else {
      const n = held.length;
      await alert('Call ended', `${n} call${n === 1 ? '' : 's'} on hold. Open ${config.panelName} to switch.`);
    }
  }

  function onWidget(event) {
    if (!event || event.Type !== 'clicked') return;
    const id = event.WidgetId || '';
    if (id === WIDGET_NEW) return askForNewCall();
    if (id.startsWith(WIDGET_SWITCH)) return switchTo(id.slice(WIDGET_SWITCH.length));
    if (id.startsWith(WIDGET_END)) return endCall(id.slice(WIDGET_END.length));
  }

  function onTextInput(event) {
    if (event && event.FeedbackId === FEEDBACK_DIAL) return dial(event.Text);
  }

  async function start() {
    const current = await xapi.Status.Call.get().catch(() => []);
    applyStatus(current || []);
    xapi.Status.Call.on(onStatus);
    xapi.Event.UserInterface.Extensions.Widget.Action.on(onWidget);
    xapi.Event.UserInterface.Message.TextInput.Response.on(onTextInput);
    await render();
  }

  return { start, switchTo, endCall, dial, getCalls, getCall, render };
}

if (globalThis.__CALL_SWITCHER_TEST__) {
  globalThis.__callSwitcher = { createCallSwitcher };
} else {
  createCallSwitcher(xapi).start();
}
