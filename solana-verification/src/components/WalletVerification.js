import React, { useState, Suspense } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { WalletMultiButton } from '@solana/wallet-adapter-react-ui';
import { useSearchParams } from 'react-router-dom';
import { API_URL } from '../config';
import './WalletVerification.css';

require('@solana/wallet-adapter-react-ui/styles.css');

const LoadingSpinner = () => (
    <div className="loading-spinner">
        <div className="spinner"></div>
        <p>Loading wallet connection...</p>
    </div>
);

const WalletVerification = () => {
    const { publicKey, connected, signMessage } = useWallet();
    const [searchParams] = useSearchParams();
    const [status, setStatus] = useState('idle');
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');
    const userId = searchParams.get('userId');

    const handleVerification = async () => {
        if (!connected || !publicKey) {
            setError('Please connect your wallet first');
            return;
        }

        try {
            setStatus('verifying');
            // Get the public key in base58 format
            const walletPublicKey = publicKey.toString();

            // Create the verification message
            const verificationMessage = `Verify ownership of Solana address ${walletPublicKey} for Telegram user ${userId}`;
            const messageBytes = new TextEncoder().encode(verificationMessage);

            // Sign the message
            const signature = await signMessage(messageBytes);
            // Convert Uint8Array to base64 string using browser-compatible method
            const signatureBase64 = btoa(String.fromCharCode.apply(null, signature));

            // Prepare the request data
            const requestData = {
                user_id: parseInt(userId),
                message: verificationMessage,
                signature: signatureBase64,
                publicKey: walletPublicKey
            };

            // Send the verification request
            const response = await fetch(`${API_URL}/api/verify`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData)
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || `Server error: ${response.status}`);
            }

            if (data.success) {
                setStatus('success');
                setMessage('Address verified successfully! You can now close this window and return to Telegram.');
            } else {
                throw new Error(data.message || 'Verification failed');
            }
        } catch (error) {
            console.error('Verification error:', error);
            setError(error.message || 'An error occurred during verification');
            setStatus('error');
        }
    };

    return (
        <Suspense fallback={<LoadingSpinner />}>
            <div className="container">
                <h1>Solana Wallet Verification</h1>
                {status === 'verifying' ? (
                    <div className="verifying-section">
                        <LoadingSpinner />
                        <p>Verifying your address...</p>
                    </div>
                ) : status === 'success' ? (
                    <div className="success-section">
                        <p>{message}</p>
                    </div>
                ) : error ? (
                    <div className="error-section">
                        <p>Error: {error}</p>
                        <button onClick={() => {
                            setError('');
                            setStatus('idle');
                        }}>Try Again</button>
                    </div>
                ) : (
                    <div className="connect-section">
                        <p>{connected 
                            ? `Connected with wallet: ${publicKey?.toString().slice(0, 4)}...${publicKey?.toString().slice(-4)}`
                            : 'Please connect your wallet to verify your address.'
                        }</p>
                        <div className="button-container">
                            <WalletMultiButton />
                            {connected && (
                                <button 
                                    className="sign-button"
                                    onClick={handleVerification}
                                >
                                    Sign & Verify
                                </button>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </Suspense>
    );
};

export default WalletVerification; 