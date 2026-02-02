# Player currency save notes

## What the player file contains
The `player` save file at the repo root is base64-encoded binary data. When decoded, it contains a set of protobuf-like entries under `player_inventory` with names like `gold`, `lucky_coin`, and `friendship_essence`.

Each entry is a small message that looks like:

```
1a <len> 0a <len> <name> 10 01 18 <varint> 30 01
```

The `<varint>` after the `0x18` tag is the stored currency value.

## Why the numbers look huge
In the current save, the stored values for the three currencies are much larger than the in-game counts:

- `gold` (Snoutlings): **195225736**
- `lucky_coin`: **195225780**
- `friendship_essence`: **195225776**

Given the in-game counts (16 Lucky Coins, 75 Snoutlings, 11 Friendship Essence), the save file is using a per-currency additive offset:

```
stored_value = actual_value + offset
```

From this save file:

- `gold` offset = 195225736 - 75 = **195225661**
- `lucky_coin` offset = 195225780 - 16 = **195225764**
- `friendship_essence` offset = 195225776 - 11 = **195225765**

To set a new desired in-game value, reuse the offset for that currency:

```
new_stored_value = desired_value + offset
```

## Helper script
The repo now includes a small helper script to extract the stored values and compute offsets, and to write an updated save if you supply the current in-game values.

Example usage (read-only):

```
python tools/save_currency_offsets.py --input player \
  --actual gold=75 --actual lucky_coin=16 --actual friendship_essence=11
```

Example usage (write a new save with updated amounts):

```
python tools/save_currency_offsets.py --input player \
  --actual gold=75 --actual lucky_coin=16 --actual friendship_essence=11 \
  --set gold=999 --set lucky_coin=250 --set friendship_essence=99 \
  --output player.updated
```

The output file is base64-encoded and can replace the original `player` save file after backup.
