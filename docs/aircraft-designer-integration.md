# FlightCost ↔ OpenAircraftCreator (Stage 2, opt-in)

**Off by default.** `FCA_AIRCRAFT_DESIGNER=1` enables the additional 3D
section on existing public type pages and the guest-only
`POST /api/aircraft/designer-save` endpoint. With the switch absent, the
existing SEO type page, editor, API and calculation paths are unchanged.

## Version 1 exchange

The type page uses a pinned copy of Aircraft Designer's v1 catalog at
`flightcostapp/web/aircraft-configurations.v1.json` to offer only real
model/engine/weight-profile/layout combinations. The 3D site gets the exact
selection through URL parameters; a normal, non-module browser script opens
it in an iframe.

The iframe's `DESIGN_EXPORT` is accepted only when **both** the origin is
`https://aircraft-designer.app` **and** `event.source` is the current iframe.
The protocol/version/ICAO/engine/row-count/masses are checked in the browser
and again on FlightCost's server. A `DESIGN_ACK(saved:true)` is posted only
after a guest-workspace write is committed and read back.

Only the owner of an existing guest workspace can save; no source catalog or
another workspace is changed. The server reuses the existing type parser and
`GuestDB` overlay. Repeated messages with the same `requestId` and identical
payload return the previously saved user type; changed payloads cannot
silently overwrite the previous version. The new endpoint requires the exact
same-origin `Origin` header and JSON content type. No new standalone service
or browser-side JavaScript module is required.

## Engineering / economics boundary

- The model is **provisional**. Cabin row counts become `seats_typical`,
  and OEW, MTOW, MLW, geometry and fuel tank capacity are saved in the
  existing aircraft type fields. The full cabin and `MZFW` are retained in
  `aircraft_designer` workspace metadata. **The current FlightCost economy
  engine does not enforce MZFW or reproduce the 3D mission solver.**
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

## Deployment safety

Existing `deploy/deploy.sh` resets the server working tree to `origin/main`
and restarts `fca`. GitHub Actions deploys **every push to `main`** after
passing tests. Review on a feature branch/PR first; never deploy by
force-pushing `main`. Merely merging the code is not activation because the
feature flag is disabled by default.

Enable only after checking the Aircraft Designer CSP `frame-ancestors` allows
`https://flightcost.app` and testing browser interaction in an actual HTTPS
session. Use a *separate* systemd drop-in on the FlightCost server:

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
validate iframe loading, theme, mobile sizing, workspace link and calculation
in a preview before switching on production.
