# Maps

{mod}`macos.maps` turns an address into coordinates, and coordinates into an
address, as the Maps app does.

```python
import macos

place = macos.maps.geocode("20 W 34th St, New York, NY")[0]
place.latitude, place.longitude              # (40.748479, -73.985411)

macos.maps.reverse_geocode(48.8584, 2.2945)  # Place(name='Eiffel Tower', city='Paris', ...)
```

It goes through Apple's geocoding service: it needs the internet, but no
permission, not even Location.

## From an address

{func}`~macos.maps.geocode` returns the places matching an address, the
likeliest first, or `[]`. Any address works, whole or in part, in any
language; names come back in the system's language:

```python
for place in macos.maps.geocode("1 Infinite Loop, Cupertino"):
    print(place.street, place.city, place.state, place.country_code)   # 1 Infinite Loop Cupertino CA US
```

Each {class}`~macos.maps.Place` has its `name`, `street` (written as the
country writes it), `city`, `state`, `postal_code`, `country`,
`country_code`, `latitude`, `longitude` and `time_zone`. The service guesses
rather than give up: for vague addresses, check the place's `country_code`
or `city`.

## From coordinates

{func}`~macos.maps.reverse_geocode` returns the address at a point, or `None`
when macOS finds nothing there:

```python
place = macos.maps.reverse_geocode(37.8199, -122.4783)
place.city, place.time_zone   # ('San Francisco', 'America/Los_Angeles')
```

Out at sea, it's the ocean's name, without an address.

## The Maps app

{func}`~macos.maps.open` shows a place in the Maps app, and
{func}`~macos.maps.directions` opens it with the route:

```python
macos.maps.open("20 W 34th St, New York, NY")
macos.maps.open(macos.maps.geocode("Eiffel Tower")[0])

macos.maps.directions("JFK Airport", by="transit")   # from where the Mac is
macos.maps.directions((48.8584, 2.2945), start="Gare du Nord, Paris", by="walk")
```

A place is an address, a {class}`~macos.maps.Place` or `(latitude, longitude)`,
with the latitude from -90 to 90 and the longitude from -180 to 180;
`by` is `"car"`, `"walk"` or `"transit"`.

## Limits

Apple limits how many requests an app makes in a short time: space out
large batches, or a request raises {class}`~macos.MacOSError`. A request
that gets no answer within `timeout` seconds (15 by default) raises
{class}`~macos.WaitTimeoutError` (a `TimeoutError`); `timeout` must be a
positive number. A request that times out, or that Ctrl-C interrupts, is
canceled, and its answer is dropped when it comes. Call these functions from the main thread, where the answers
arrive.

## Reference

- {func}`macos.maps.geocode`
- {func}`macos.maps.reverse_geocode`
- {class}`macos.maps.Place`
- {func}`macos.maps.open`
- {func}`macos.maps.directions`
