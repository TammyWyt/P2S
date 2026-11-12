"""E13 ground-truth protocol labels. These read HIDDEN fields (to, selector, value, emitted
events), so they are used only as labels, never as features. The same function labels the
window transactions and the history transactions, so a sender's history uses one definition."""
import os, re

_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'revert_cost_analysis.py')).read()
_blk = _src[_src.index('DEX_ROUTERS = {'):_src.index('}', _src.index('DEX_ROUTERS = {'))]
DEX_ROUTERS = dict(re.findall(r'"(0x[0-9a-f]{40})":\s*"([^"]+)"', _blk))
DEX_ROUTERS.update({'0x80a64c6d7f12c47b7c66c5b4e20e72bc1fcd5d9e': 'Maestro',
                    '0x3328f7f4a1d1c57c35df56bbf0c9dcafca309c49': 'BananaGun'})
WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'

DEX_OTHER = {  # non-Uniswap swap events (Uniswap V2/V3/V4 come from the swap legs L)
    '0x8b3e96f2b889fa771c53c981b40daf005f63f637f1869f707052d15a3dd97140',  # Curve TokenExchange
    '0xd013ca23e77a65003c2c659c5442c00c805371b7fc1ebd4c206c41d1536bd90b',  # Curve TokenExchangeUnderlying
    '0xb2e76ae99761dc136e598d4a629bb347eccb9532a5f8bbd72e18467c3c34cc98',  # Curve v2 TokenExchange
    '0x2170c741c41531aec20e7c107c24eecfdd15e69c9bb0a8dd37b1840b9e0b207b',  # Balancer V2 Swap
}
LENDING = {
    '0x2b627736bca15cd5381dcf80b0bf11fd197d01a037c52b927a881a10fb73ba61',  # Aave v3 Supply
    '0xde6857219544bb5b7746f48ed30be6386fefc61b2f864cacf559893bf50fd951',  # Aave v2 Deposit
    '0xb3d084820fb1a9decffb176436bd02558d15fac9b0ddfed8c465bc7359d7dce0',  # Aave v3 Borrow
    '0xc6a898309e823ee50bac64e45ca8adba6690e99e7841c45d754e2a38e9019d9b',  # Aave v2 Borrow
    '0xa534c8dbe71f871f9f3530e97a74601fea17b426cae02e1c5aee42c96c784051',  # Aave v3 Repay
    '0x4cdde6e09bb755c9a5589ebaec640bbfedff1362d4b255ebf8339782b9942faa',  # Aave v2 Repay
    '0x3115d1449a7b732c986cba18244e897a450f61e1bb8d589cd2e69e6c8924f9f7',  # Aave Withdraw
    '0xe413a321e8681d831f4dbccbca790d2952b56f977908e45be37335533e005286',  # Aave LiquidationCall
    '0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f',  # Compound v2 Mint
    '0xe5b754fb1abb7f01b499791d0b820ae3b6af3424ac1c59768edb53f4ec31a929',  # Compound v2 Redeem
}
NFT = {'0x9d9af8e38d66c62e2c12f0225249fd9d721c54b83f48d9352c97c6cacdcb6f31'}  # Seaport OrderFulfilled
AA = {'0x49628fd1471006c1482da88028e9ce4dbb080b815c9b0344d39e5a8e6ec1419f',   # ERC-4337 v0.6
      '0xb8acd7610deb116bbfa857befeb2e6562d6970296b724ca9f9f2cc5a1b95d63c'}   # ERC-4337 v0.7
TOPICS = DEX_OTHER | LENDING | NFT | AA

CLASSES = ['dex_swap', 'lending', 'nft', 'aa_bundle', 'weth_wrap', 'approve',
           'erc20_transfer', 'eth_transfer', 'other_call']
CID = {c: i for i, c in enumerate(CLASSES)}


def protocol(to, sel, L, topics):
    """Hidden-field label. Priority order resolves txs that touch several protocols."""
    if topics & AA or sel in ('0x1fad948c', '0x765e827f'):
        return 'aa_bundle'
    if L or topics & DEX_OTHER or to in DEX_ROUTERS:
        return 'dex_swap'
    if topics & LENDING:
        return 'lending'
    if topics & NFT:
        return 'nft'
    if to == WETH and sel in ('0xd0e30db0', '0x2e1a7d4d'):
        return 'weth_wrap'
    if sel == '0x095ea7b3':
        return 'approve'
    if sel in ('0xa9059cbb', '0x23b872dd'):
        return 'erc20_transfer'
    if sel in ('0x', ''):
        return 'eth_transfer'
    return 'other_call'
