import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createFakeXapi, flush } from './fake-xapi.js';
import '../macro/call-switcher.js';

const { createCallSwitcher } = globalThis.__callSwitcher;

async function setup(calls = []) {
  const fake = createFakeXapi();
  fake.setStatus('Status.Call', calls);
  const switcher = createCallSwitcher(fake.xapi);
  await switcher.start();
  return { fake, switcher };
}

function lastPanel(fake) {
  const saves = fake.sent('Command.UserInterface.Extensions.Panel.Save');
  return saves.length ? saves[saves.length - 1].body : '';
}

function click(fake, widgetId) {
  return fake.emit('Event.UserInterface.Extensions.Widget.Action', {
    WidgetId: widgetId,
    Type: 'clicked',
    Value: '',
  });
}

const alice = { id: '1', DisplayName: 'Alice', RemoteNumber: 'alice@example.com', Status: 'Connected', CallType: 'Video' };
const bob = { id: '2', DisplayName: 'Bob', RemoteNumber: 'bob@example.com', Status: 'OnHold', CallType: 'Video' };

test('loads existing calls on start and draws the panel', async () => {
  const { fake, switcher } = await setup([alice, bob]);
  assert.deepEqual(switcher.getCalls().map((c) => c.id), ['1', '2']);
  const xml = lastPanel(fake);
  assert.match(xml, /<PanelId>call_switcher<\/PanelId>/);
  assert.match(xml, /Alice/);
  assert.match(xml, /Bob/);
  assert.match(xml, /cs_switch_2/);
  // The call you're already in has no "switch" button.
  assert.doesNotMatch(xml, /cs_switch_1/);
});

test('switching holds the live call before resuming the chosen one', async () => {
  const { fake } = await setup([alice, bob]);
  fake.clear();
  await click(fake, 'cs_switch_2');
  const order = fake.commands
    .filter((c) => c.path === 'Command.Call.Hold' || c.path === 'Command.Call.Resume')
    .map((c) => `${c.path.split('.').pop()} ${c.args.CallId}`);
  assert.deepEqual(order, ['Hold 1', 'Resume 2']);
});

test('switching to the call you are already in does nothing', async () => {
  const { fake, switcher } = await setup([alice, bob]);
  fake.clear();
  await switcher.switchTo('1');
  assert.equal(fake.sent('Command.Call.Hold').length, 0);
  assert.equal(fake.sent('Command.Call.Resume').length, 0);
});

test('ignores a second tap while a switch is still in progress', async () => {
  const { fake, switcher } = await setup([alice, bob, { ...bob, id: '3', DisplayName: 'Cara' }]);
  let release;
  fake.onCommand('Command.Call.Hold', () => new Promise((r) => (release = r)));
  fake.clear();
  const first = switcher.switchTo('2');
  await flush();
  await switcher.switchTo('3');
  release({});
  await first;
  assert.deepEqual(fake.sent('Command.Call.Resume').map((c) => c.args.CallId), ['2']);
});

test('shows an alert if the device refuses the switch', async () => {
  const { fake } = await setup([alice, bob]);
  fake.onCommand('Command.Call.Resume', () => {
    throw new Error('Resume not allowed');
  });
  await click(fake, 'cs_switch_2');
  const alerts = fake.sent('Command.UserInterface.Message.Alert.Display');
  assert.equal(alerts.length, 1);
  assert.match(alerts[0].args.Text, /Resume not allowed/);
});

test('status updates change the call list and redraw the panel', async () => {
  const { fake, switcher } = await setup([alice, bob]);
  await fake.emit('Status.Call', { id: '1', Status: 'OnHold' });
  await fake.emit('Status.Call', { id: '2', Status: 'Connected' });
  assert.equal(switcher.getCall('1').held, true);
  assert.equal(switcher.getCall('2').held, false);
  const xml = lastPanel(fake);
  assert.match(xml, /cs_switch_1/);
  assert.doesNotMatch(xml, /cs_switch_2/);
});

test('a call that ends is removed from the list', async () => {
  const { fake, switcher } = await setup([alice, bob]);
  await fake.emit('Status.Call', { id: '2', ghost: 'True' });
  assert.deepEqual(switcher.getCalls().map((c) => c.id), ['1']);
  assert.doesNotMatch(lastPanel(fake), /Bob/);
});

test('a call held with PlacedOnHold counts as held', async () => {
  const { switcher } = await setup([{ ...alice, Status: 'Connected', PlacedOnHold: 'True' }]);
  assert.equal(switcher.getCall('1').held, true);
});

test('when the live call ends, held calls stay on hold and the user is told', async () => {
  const { fake, switcher } = await setup([alice, bob]);
  fake.clear();
  await fake.emit('Status.Call', { id: '1', ghost: 'True' });
  assert.equal(fake.sent('Command.Call.Resume').length, 0);
  assert.equal(switcher.getCall('2').held, true);
  const alerts = fake.sent('Command.UserInterface.Message.Alert.Display');
  assert.equal(alerts.length, 1);
  assert.match(alerts[0].args.Text, /1 call on hold/);
});

test('end button disconnects that call', async () => {
  const { fake } = await setup([alice, bob]);
  await click(fake, 'cs_end_2');
  assert.deepEqual(fake.sent('Command.Call.Disconnect').map((c) => c.args.CallId), ['2']);
});

test('new call asks for an address, holds the live call, then dials', async () => {
  const { fake } = await setup([alice]);
  await click(fake, 'cs_new');
  const prompt = fake.sent('Command.UserInterface.Message.TextInput.Display');
  assert.equal(prompt.length, 1);
  const feedbackId = prompt[0].args.FeedbackId;

  fake.clear();
  await fake.emit('Event.UserInterface.Message.TextInput.Response', {
    FeedbackId: feedbackId,
    Text: ' carol@example.com ',
  });
  const order = fake.commands
    .filter((c) => c.path === 'Command.Call.Hold' || c.path === 'Command.Dial')
    .map((c) => c.path);
  assert.deepEqual(order, ['Command.Call.Hold', 'Command.Dial']);
  assert.equal(fake.sent('Command.Dial')[0].args.Number, 'carol@example.com');
});

test('an empty address does not dial', async () => {
  const { fake } = await setup([alice]);
  await click(fake, 'cs_new');
  const feedbackId = fake.sent('Command.UserInterface.Message.TextInput.Display')[0].args.FeedbackId;
  await fake.emit('Event.UserInterface.Message.TextInput.Response', { FeedbackId: feedbackId, Text: '   ' });
  assert.equal(fake.sent('Command.Dial').length, 0);
  assert.equal(fake.sent('Command.Call.Hold').length, 0);
});

test('caller names are escaped in the panel XML', async () => {
  const { fake } = await setup([{ ...alice, DisplayName: 'R&D <Lab>' }]);
  const xml = lastPanel(fake);
  assert.match(xml, /R&amp;D &lt;Lab&gt;/);
  assert.doesNotMatch(xml, /R&D <Lab>/);
});

test('falls back to the number when a call has no display name', async () => {
  const { fake } = await setup([{ ...alice, DisplayName: '' }]);
  assert.match(lastPanel(fake), /alice@example\.com/);
});

test('panel says so when there are no calls', async () => {
  const { fake } = await setup([]);
  assert.match(lastPanel(fake), /No calls/);
});

test('does not resend an identical panel', async () => {
  const { fake } = await setup([alice, bob]);
  const before = fake.sent('Command.UserInterface.Extensions.Panel.Save').length;
  await fake.emit('Status.Call', { id: '1', Status: 'Connected' });
  assert.equal(fake.sent('Command.UserInterface.Extensions.Panel.Save').length, before);
});
