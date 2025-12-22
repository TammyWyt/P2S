# P2S (Proposer in 2 Steps) Consensus Protocol

A novel consensus mechanism designed to mitigate MEV (Maximal Extractable Value) attacks through a two-step block proposal process with hidden transaction details.

## Overview

P2S implements a **two-step block proposal mechanism** where:
1. **B1 Block**: Contains PHTs (Partially Hidden Transactions) with concealed sensitive fields
2. **B2 Block**: Contains MTs (Matching Transactions) with revealed details after B1 confirmation

This design prevents MEV attacks by hiding transaction details until after block commitment, while maintaining compatibility with Ethereum's consensus mechanism.


