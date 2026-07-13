package main


import (
    "errors"
    "fmt"
    "time"


    "github.com/bytedance/sonic"
    "github.com/byteplus-sdk/byteplus-go-sdk-v2/byteplus"
    "github.com/byteplus-sdk/byteplus-go-sdk-v2/byteplus/credentials"
    "github.com/byteplus-sdk/byteplus-go-sdk-v2/byteplus/session"
    "github.com/byteplus-sdk/byteplus-go-sdk-v2/byteplus/universal"
)


const (
    region      = "ap-southeast-1"
    serviceName = "ark"
    version     = "2024-01-01"


    // Configure polling
    pollInterval = 3 * time.Second
    pollTimeout  = 60 * time.Minute
)


func main() {
    // TODO: Replace with your AK / SK
    ak := "<YOUR_AK>"
    sk := "<YOUR_SK>"


    // TODO: Set to the parameters that you need to use
    groupID := "group-20260324142802-*****"
    assetURL := "<IMAGE_URL>"
    assetType := "Image"
    projectName := "default"


    config := byteplus.NewConfig().
        WithCredentials(credentials.NewStaticCredentials(ak, sk, "")).
        WithRegion(region)


    sess, err := session.NewSession(config)
    if err != nil {
        fmt.Printf("create session failed: %v\n", err)
        return
    }


    client := universal.New(sess)


    // 1. Create asset
    assetID, err := createAsset(client, groupID, assetURL, assetType, projectName)
    if err != nil {
        fmt.Printf("create asset failed: %v\n", err)
        return
    }


    fmt.Printf("asset created, AssetId = %s\n", assetID)


    // 2. Query asset status
    finalURL, err := waitForAssetActive(client, assetID, pollInterval, pollTimeout)
    if err != nil {
        fmt.Printf("poll asset failed: %v\n", err)
        return
    }


    fmt.Printf("asset is active, URL = %s\n", finalURL)
}


// Call CreateAsset and return Asset Id
func createAsset(client *universal.Universal, groupID, url, assetType, projectName string) (string, error) {
    resp, err := client.DoCall(
        universal.RequestUniversal{
            ServiceName: serviceName,
            Action:      "CreateAsset",
            Version:     version,
            HttpMethod:  universal.POST,
            ContentType: universal.ApplicationJSON,
        },
        &map[string]any{
            "GroupId":     groupID,
            "URL":         url,
            "AssetType":   assetType,
            "ProjectName": projectName,
        },
    )
    if err != nil {
        return "", err
    }
    if resp == nil {
        return "", errors.New("create asset response is nil")
    }


    // Print the response
    respData, _ := sonic.Marshal(resp)
    fmt.Printf("CreateAsset response: %s\n", string(respData))


    assetID := extractString(resp, "Result", "Id")
    if assetID == "" {
        assetID = extractString(resp, "Result", "AssetId")
    }
    if assetID == "" {
        assetID = extractString(resp, "Id")
    }
    if assetID == "" {
        assetID = extractString(resp, "AssetId")
    }


    if assetID == "" {
        return "", fmt.Errorf("cannot find AssetId in response: %s", string(respData))
    }


    return assetID, nil
}


// waitForAssetActive: query GetAsset until Active / Failed / Timeout
func waitForAssetActive(client *universal.Universal, assetID string, interval, timeout time.Duration) (string, error) {
    deadline := time.Now().Add(timeout)


    for {
        if time.Now().After(deadline) {
            return "", fmt.Errorf("polling timeout after %v, assetID=%s", timeout, assetID)
        }


        status, url, errMsg, err := getAssetStatus(client, assetID)
        if err != nil {
            return "", err
        }


        fmt.Printf("asset status: %s\n", status)


        switch status {
        case "Processing":
            time.Sleep(interval)
            continue
        case "Active":
            if url == "" {
                return "", fmt.Errorf("asset is Active but URL is empty, assetID=%s", assetID)
            }
            return url, nil
        case "Failed":
            if errMsg == "" {
                errMsg = "unknown asset processing error"
            }
            return "", fmt.Errorf("asset processing failed: %s", errMsg)
        default:
            fmt.Printf("unexpected status %q, continue polling...\n", status)
            time.Sleep(interval)
        }
    }
}


// getAssetStatus: query GetAsset, return Status / URL / Error
func getAssetStatus(client *universal.Universal, assetID string) (status, url, errMsg string, err error) {
    resp, err := client.DoCall(
        universal.RequestUniversal{
            ServiceName: serviceName,
            Action:      "GetAsset",
            Version:     version,
            HttpMethod:  universal.POST,
            ContentType: universal.ApplicationJSON,
        },
        &map[string]any{
            "Id": assetID,
        },
    )
    if err != nil {
        return "", "", "", err
    }
    if resp == nil {
        return "", "", "", errors.New("get asset response is nil")
    }


    // Print response
    respData, _ := sonic.Marshal(resp)
    fmt.Printf("GetAsset response: %s\n", string(respData))


    status = extractString(resp, "Result", "Status")
    if status == "" {
        status = extractString(resp, "Status")
    }


    url = extractString(resp, "Result", "URL")
    if url == "" {
        url = extractString(resp, "URL")
    }


    errMsg = extractString(resp, "Result", "Error")
    if errMsg == "" {
        errMsg = extractString(resp, "Error")
    }


    return status, url, errMsg, nil
}


// extractString
func extractString(data any, keys ...string) string {
    current := data


    for _, key := range keys {
        switch v := current.(type) {
        case map[string]any:
            next, ok := v[key]
            if !ok {
                return ""
            }
            current = next


        case *map[string]any:
            if v == nil {
                return ""
            }
            next, ok := (*v)[key]
            if !ok {
                return ""
            }
            current = next


        default:
            return ""
        }
    }


    switch v := current.(type) {
    case string:
        return v
    case fmt.Stringer:
        return v.String()
    case nil:
        return ""
    default:
        return fmt.Sprintf("%v", v)
    }
}