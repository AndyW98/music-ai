# Call Switcher for Cisco room devices

A RoomOS macro that lets you be in several calls at once and switch between
them from the touch panel, like switching between chats.

Only the call you're viewing is live. Every other call is put **on hold**, so
the device isn't receiving or decoding video you can't see. Switching holds
the current call first and then resumes the one you picked, so two calls are
never live at the same time.

Built for the **Cisco Room Bar Pro**. It only uses standard RoomOS xAPI
commands, so it should also run on other RoomOS 11 devices (Room Bar, Board
Pro, Desk Pro, Room Kit EQ, Room Kit Pro), but it has only been tested
against a simulated device so far (see [Status](#status)).

## What it does

A **Calls** button appears on the home screen and in the call controls. It
opens a panel listing every call:

```
┌ Calls ─────────────────────────────────────┐
│ Alice        In call               [ End ] │
│ Bob          On hold   [ Switch ]  [ End ] │
│ Carol        On hold   [ Switch ]  [ End ] │
│                                            │
│              [        New call        ]    │
└────────────────────────────────────────────┘
```

- **Switch**: puts the current call on hold and resumes this one.
- **End**: hangs up this call.
- **New call**: asks for a name, number or video address, puts the current
  call on hold, then dials.
- If the call you're in ends while others are on hold, they **stay on hold**
  and an alert tells you how many are waiting. Set `autoResumeOnHangUp: true`
  in the macro's `DEFAULTS` to resume the oldest held call automatically.

## Install

1. Open the device's web interface and go to **Customization > Macro Editor**.
   (For devices in Webex Control Hub, macros can also be uploaded there once
   macro provisioning is turned on.)
2. Create a new macro, paste in [`macro/call-switcher.js`](macro/call-switcher.js),
   save it and switch it on.
3. The **Calls** panel appears on the touch controller. The macro creates it
   itself, so you don't need to import a separate UI Extensions file.

To remove it, switch off or delete the macro, then delete the
`call_switcher` panel in **Customization > UI Extensions Editor**.

## Requirements and limits

- **RoomOS 11 or later.** The macro is a plain ES module with no
  transpilation, which matches Cisco's move of the macro runtime to QuickJS.
- **How many calls you can hold depends on the device's licence.** Community
  reports say devices *without* the Multisite option allow one video call
  plus one audio call; a second video call is forced to audio only, and one
  user on newer firmware said even that didn't work. Devices *with*
  Multisite can hold more. If the device refuses a call, the macro shows
  the device's error message instead of failing silently.
- **Held callers can't see or hear the room**, and you can't hear them. This
  is what saves the device's processing, and it's the intended design.
- **Standard calling mode only.** It has not been checked on devices running
  Microsoft Teams Rooms or Zoom Rooms mode.
- **Webex meetings** may not behave like plain SIP calls when placed on hold.
  This needs checking on a real device.

## Status

The logic is covered by automated tests against a simulated `xapi`, but
**it has not yet run on real hardware**. Before deploying, check on a Room
Bar Pro:

- [ ] The panel appears and the layout looks right.
- [ ] Switching between two SIP video calls works, and the held call stops
      sending video.
- [ ] How long video takes to return after a switch.
- [ ] Behaviour with and without the Multisite option.
- [ ] Behaviour with a Webex meeting as one of the calls.
- [ ] Behaviour when a call comes in while you're already in one.

## Development

Needs Node.js 20 or later. There are no dependencies to install.

```sh
npm test
```

The tests load the macro with a fake `xapi` (`test/fake-xapi.js`) that
records every command the macro sends and lets tests fire status changes and
touch-panel events.
