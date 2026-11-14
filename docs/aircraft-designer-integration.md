# FlightCost ↔ OpenAircraftCreator (Stage 2, opt-in)

**Off by default.** `FCA_AIRCRAFT_DESIGNER=1` adds a small 3D navigation
form to existing public type pages plus a dedicated full-height page at
`/{lang}/type/{ICAO}/3d?choice=<index>`, and enables the guest-only
`POST /api/aircraft/designer-save` endpoint. With the switch absent, the
existing SEO type page, editor, API and calculation paths are unchanged.

## Version 1 exchange

The type page uses a pinned copy of Aircraft Designer's v1 catalog at
`flightcostapp/web/aircraft-configurations.v1.json` to offer only real
model/engine/weight-profile/layout combinations. The canonical type card
only links to the dedicated FlightCost page via an ordinary GET form; it does
not load a 3D iframe or run the bridge. The separate page occupies the viewport,
loads Aircraft Designer into a full-size iframe, and has a persistent back link
to the reference type card and a native layout/engine selector. This is not a
modal or a new standalone server. The FlightCost origin remains top-level so
its guest workspace cookie is first-party. Selecting another configuration
reloads the 3D page and discards unsaved edits (clearly indicated).

The iframe's `DESIGN_EXPORT` is accepted only when **both** the origin is
`https://aircraft-designer.app` **and** `event.source` is the current iframe.
The protocol/version/ICAO/engine/row-count/masses are checked in the browser
and again on FlightCost's server. A `DESIGN_ACK(saved:true)` is posted only
after a guest-workspace write is committed and read back.

Only the owner of an existing guest workspace can save; no source catalog or
another workspace is changed. If the workspace is created from the 3D page,
its secret access link is retained visibly even after saving. After confirmed
persistence the user can return to the type card, open their workspace, and
(with an inherited fuel model or an available Designer route model) open the route calculator with the new
`USER:...` aircraft code. The server reuses the existing type parser and
`GuestDB` overlay. Repeated messages with the same `requestId` and identical
payload return the previously saved user type; changed payloads cannot
silently overwrite the previous version. The new endpoint requires the exact
same-origin `Origin` header and JSON content type. No new standalone service
or browser-side JavaScript module is required.

## Engineering / economics boundary

- The model is **provisional**. Cabin row counts become `seats_typical`,
  and OEW, MTOW, MLW, geometry and fuel tank capacity are saved in the
  existing aircraft type fields. The full cabin and `MZFW` are retained in
  `aircraft_designer` workspace metadata. The A320ceo/CFM56-5B and A320neo/LEAP-1A route adapter enforces MZFW when it replays the saved design.
- `seats_max` is retained from the original published type unless the new
  user configuration has more seats. If exceeded, the **original passport
  maximum** and explicit non-certified over-capacity status remain in
  `aircraft_designer` metadata. `seats_typical` is always the physical cabin
  from the 3D export; do not label the new `seats_max` as certified.
- A FlightCost fuel model is inherited only when the **exact engine** matches
  (PS-90A / ПС-90А is the one explicit alias). For a different engine, the
  original burn/analog record is dropped. In particular, LEAP-1A must not
  claim the PW1127G-JM fuel model. Even a same-engine estimate is only an
  existing FlightCost approximation, not a performance certification for an
  altered airframe.
- Catalog revisions require a coordinated change on **both** sites. The
  snapshot is pinned deliberately; there is no runtime cross-domain catalog
  fetch that could change contracts silently.

## Local A320ceo and A320neo route calculation

Use Node 22.18 or later and the corresponding Designer checkout. Run these commands in two terminals. Choose a reference database for the preview. Guest aircraft are saved in `user.db` next to that database.

In Aircraft Designer:

```sh
VITE_FLIGHTCOST_ORIGIN=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 8001 --strictPort
```

In FlightCost:

```sh
FCA_AIRCRAFT_DESIGNER=1 FCA_DESIGNER_ORIGIN=http://127.0.0.1:8001 \
  FCA_DESIGNER_RUNNER=/absolute/path/to/openaircraftcreator/scripts/flightcost-route.ts \
  fca --db /absolute/path/to/flightcost.db serve --guests --port 8000
```

Open `http://127.0.0.1:8000/ru/type/A320/3d?choice=0` for the 180-seat CFM56-5B or `http://127.0.0.1:8000/ru/type/A20N/3d?choice=1` for the 194-seat LEAP-1A. Select a load, save to the guest workspace and follow the route link. The runner reconstructs the saved control settings, mode and cabin. It accepts earlier v1 exports when their geometry and masses can be reproduced. An incompatible design or unavailable runner returns a calculation error.

The FRA–BCN review uses the FlightCost route distance including its ICAO correction and 100 kg per passenger including baggage. The reported consumption includes taxi fuel. The Designer mission carries a separate reserve with a default 200 nm alternate, 30-minute final reserve and 5% contingency. Cruise time uses the speed of each integrated step. The reference CFM56-5B uses the available FCOM phase times, including the six-minute IFR approach after descent to 1,500 ft. Energy-based phases use 300 kt for climb and 280 kt for descent. Both profiles use a combined taxi time of 26 minutes.

## Deployment safety

The two sites run on separate hosts. `DESIGNER_REVISION` pins the backend solver to the reviewed Aircraft Designer commit. The FlightCost deploy script installs that checkout under `/srv/fca/designer/<commit>` and verifies Node 22.18+ before restarting the service. Publish the corresponding Designer static build with its normal `deploy/ship.sh`. The local `FCA_DESIGNER_RUNNER` override is optional on the server.

Existing `deploy/deploy.sh` resets the server working tree to `origin/main`
and restarts `fca`. GitHub Actions deploys **every push to `main`** after
passing tests. Review on a feature branch/PR first; never deploy by
force-pushing `main`. Merely merging the code is not activation because the
feature flag is disabled by default.

Enable only after checking the Aircraft Designer CSP `frame-ancestors` allows
`https://flightcost.app` (and any FlightCost `frame-src` policy allows
`https://aircraft-designer.app`) and testing the `/3d` page and navigation in
an actual HTTPS session. Use a *separate* systemd drop-in on the FlightCost server:

```ini
[Service]
Environment=FCA_AIRCRAFT_DESIGNER=1
```

Inspect existing drop-ins before changing service configuration. A regular
`systemctl restart fca` after adding the drop-in activates it; removing just
this environment override and restarting turns it off without rolling back
existing workspace data.

## Tests

```sh
python3 -m pytest -q tests/test_aircraft_designer_integration.py \
    tests/test_serve_ws.py tests/test_guest.py tests/test_seo.py
node --test tests/test_aircraft_designer_bridge.cjs
python3 -m py_compile flightcostapp/aircraft_designer.py \
    flightcostapp/serve.py flightcostapp/seo.py
```

No end-to-end production-browser/Caddy assertion is performed by these tests;
validate iframe loading, theme, mobile sizing, dedicated `/3d` navigation,
workspace link and return-to-calculator link in a preview before switching
on production.
