// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

// Constant-product ETH<->TOKEN pool with internal token accounting, using the
// EXACT Uniswap V2 getAmountOut formula (0.3% fee: amountIn*997/1000). This
// makes the pool a faithful stand-in for a real Uniswap V2 pair, so replaying
// real swap sizes against real on-chain reserves reproduces real sandwich MEV.
// Reserves are set at deploy time: ethReserve = msg.value, tokenReserve = arg.
contract MiniAMM {
    uint256 public ethReserve;
    uint256 public tokenReserve;
    mapping(address => uint256) public tokenBal;

    constructor(uint256 _tokenReserve) payable {
        ethReserve = msg.value;
        tokenReserve = _tokenReserve;
    }

    // Uniswap V2 getAmountOut: out = (in*997*resOut)/(resIn*1000 + in*997).
    function _amountOut(uint256 amountIn, uint256 resIn, uint256 resOut) internal pure returns (uint256) {
        uint256 inWithFee = amountIn * 997;
        return (inWithFee * resOut) / (resIn * 1000 + inWithFee);
    }

    // Swap ETH in for TOKEN out.
    function buy() external payable {
        uint256 out = _amountOut(msg.value, ethReserve, tokenReserve);
        ethReserve += msg.value;
        tokenReserve -= out;
        tokenBal[msg.sender] += out;
    }

    // Swap TOKEN in for ETH out.
    function sell(uint256 amount) external {
        require(tokenBal[msg.sender] >= amount, "bal");
        uint256 out = _amountOut(amount, tokenReserve, ethReserve);
        tokenReserve += amount;
        ethReserve -= out;
        tokenBal[msg.sender] -= amount;
        (bool ok, ) = msg.sender.call{value: out}("");
        require(ok, "xfer");
    }
}
