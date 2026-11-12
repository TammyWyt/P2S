// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

/// Attacker legs for E13: one exact-input swap against a Uniswap V2 pair, V3 pool or V4 pool,
/// paid from this contract's own balance. Used only inside a local anvil fork.
interface IERC20 { function transfer(address, uint256) external returns (bool); function balanceOf(address) external view returns (uint256); }
interface IV2 { function getReserves() external view returns (uint112, uint112, uint32); function swap(uint256, uint256, address, bytes calldata) external; function token0() external view returns (address); function token1() external view returns (address); }
interface IV3 { function swap(address, bool, int256, uint160, bytes calldata) external returns (int256, int256); function token0() external view returns (address); function token1() external view returns (address); }

struct PoolKey { address currency0; address currency1; uint24 fee; int24 tickSpacing; address hooks; }
struct SwapParams { bool zeroForOne; int256 amountSpecified; uint160 sqrtPriceLimitX96; }
interface IPM {
    function unlock(bytes calldata) external returns (bytes memory);
    function swap(PoolKey memory, SwapParams memory, bytes calldata) external returns (int256);
    function sync(address) external;
    function settle() external payable returns (uint256);
    function take(address, address, uint256) external;
}

contract Legs {
    uint160 constant MIN_SQRT = 4295128740;
    uint160 constant MAX_SQRT = 1461446703485210103287273052203988822378723970341;
    IPM public immutable pm;
    mapping(address => uint256) public reserve;
    constructor(address _pm) { pm = IPM(_pm); }
    function setReserve(address token, uint256 amt) external { reserve[token] = amt; }
    function _bal(address token) internal view returns (uint256) {
        return (token == address(0) ? address(this).balance : IERC20(token).balanceOf(address(this))) - reserve[token];
    }
    receive() external payable {}

    function v2(address pair, bool zeroForOne, uint256 amountIn) external returns (uint256 out) {
        IV2 p = IV2(pair);
        (uint112 r0, uint112 r1,) = p.getReserves();
        (address tin, uint256 rin, uint256 rout) = zeroForOne ? (p.token0(), uint256(r0), uint256(r1)) : (p.token1(), uint256(r1), uint256(r0));
        if (amountIn == 0) amountIn = _bal(tin);
        IERC20(tin).transfer(pair, amountIn);
        uint256 got = IERC20(tin).balanceOf(pair) - rin;      // fee-on-transfer tokens deliver less
        uint256 a = got * 997;
        out = a * rout / (rin * 1000 + a);
        if (zeroForOne) p.swap(0, out, address(this), ""); else p.swap(out, 0, address(this), "");
    }

    function v3(address pool, bool zeroForOne, uint256 amountIn) external returns (uint256 out) {
        if (amountIn == 0) amountIn = _bal(zeroForOne ? IV3(pool).token0() : IV3(pool).token1());
        (int256 a0, int256 a1) = IV3(pool).swap(address(this), zeroForOne, int256(amountIn), zeroForOne ? MIN_SQRT : MAX_SQRT, abi.encode(pool));
        out = uint256(-(zeroForOne ? a1 : a0));
    }
    function uniswapV3SwapCallback(int256 a0, int256 a1, bytes calldata d) external {
        address pool = abi.decode(d, (address));
        require(msg.sender == pool, "cb");
        if (a0 > 0) IERC20(IV3(pool).token0()).transfer(pool, uint256(a0));
        if (a1 > 0) IERC20(IV3(pool).token1()).transfer(pool, uint256(a1));
    }

    /// amountIn == 0 spends the whole balance of the input currency (used by the back-run leg).
    function v4(PoolKey calldata key, bool zeroForOne, uint256 amountIn) external returns (uint256 out) {
        if (amountIn == 0) {
            amountIn = _bal(zeroForOne ? key.currency0 : key.currency1);
        }
        out = abi.decode(pm.unlock(abi.encode(key, zeroForOne, amountIn)), (uint256));
    }
    function unlockCallback(bytes calldata d) external returns (bytes memory) {
        require(msg.sender == address(pm), "pm");
        (PoolKey memory key, bool z, uint256 amt) = abi.decode(d, (PoolKey, bool, uint256));
        int256 delta = pm.swap(key, SwapParams(z, -int256(amt), z ? MIN_SQRT : MAX_SQRT), "");
        int128 d0 = int128(delta >> 128);
        int128 d1 = int128(delta);
        (address cin, address cout, int128 din, int128 dout) = z ? (key.currency0, key.currency1, d0, d1) : (key.currency1, key.currency0, d1, d0);
        uint256 pay = uint256(uint128(-din));
        if (cin == address(0)) { pm.settle{value: pay}(); }
        else { pm.sync(cin); IERC20(cin).transfer(address(pm), pay); pm.settle(); }
        uint256 o = uint256(uint128(dout));
        pm.take(cout, address(this), o);
        return abi.encode(o);
    }
}
